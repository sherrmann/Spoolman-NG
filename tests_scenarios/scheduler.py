"""Weight-aware async worker pool for running many scenarios in parallel.

Each scenario reserves `scenario.weight()` units of a shared budget before running and
gives them back afterwards, so the sum of in-flight weights never exceeds
`concurrency_budget` (e.g. a lone weight-6 armv7 scenario effectively runs alone under a
budget of 6). Kept pure/injectable via `run_one` so the scheduling logic itself can be
unit-tested with no docker involved.

Admission is implemented with an `asyncio.Condition` guarding a plain `in_flight` counter,
*not* `asyncio.Semaphore.acquire()` called `weight` times in a loop. That loop looks
tempting but is broken: CPython's `Semaphore.locked()` also reports "locked" whenever its
internal waiter deque still holds an already-resolved-but-not-yet-removed future, and
`release()` hands off exactly one unit per waiter in FIFO order. With several multi-unit
requesters contending, permits get fragmented one-at-a-time across them instead of granted
as a single atomic block, so multiple weight-6 tasks can each end up holding a partial
share with nobody left to call `release()` again -- a real, reproducible deadlock (verified
by hand: four weight-6 scenarios under budget 6 hang indefinitely with that approach). The
`Condition.wait_for` below reserves a scenario's whole weight atomically in one step, which
sidesteps that fragmentation entirely.
"""
from __future__ import annotations

import asyncio
from collections import namedtuple
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tests_scenarios.catalog import Scenario

Result = namedtuple("Result", "scenario ok detail")  # noqa: PYI024 -- interface spec calls for namedtuple


async def run_many(
    scenarios: list[Scenario],
    *,
    concurrency_budget: int,
    run_one: Callable[[Scenario], Awaitable[tuple[bool, str]]],
) -> list[Result]:
    """Run `run_one` for every scenario, admitting work while in-flight weight stays within budget.

    `run_one` exceptions are caught and turned into a failing `Result` rather than propagating,
    so one scenario's crash never aborts the others.
    """
    cond = asyncio.Condition()
    in_flight = 0

    async def worker(s: Scenario) -> Result:
        nonlocal in_flight
        weight = s.weight()
        async with cond:
            # A scenario heavier than the whole budget (e.g. weight 6 on a <6-core box)
            # would otherwise starve forever; letting it run solo (in_flight == 0) keeps
            # progress guaranteed while still never *adding* to another in-flight scenario.
            await cond.wait_for(lambda: in_flight == 0 or in_flight + weight <= concurrency_budget)
            in_flight += weight
        try:
            ok, detail = await run_one(s)
        except Exception as e:  # noqa: BLE001 -- a scenario's failure must not sink the batch
            ok, detail = False, repr(e)
        finally:
            async with cond:
                in_flight -= weight
                cond.notify_all()
        return Result(s, ok, detail)

    return list(await asyncio.gather(*(worker(s) for s in scenarios)))
