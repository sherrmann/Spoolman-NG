"""Tests for tests_scenarios.scheduler.run_many (pure -- no docker, no network)."""

from __future__ import annotations

import asyncio

import pytest

from tests_scenarios.catalog import Arch, Db, Scenario
from tests_scenarios.scheduler import run_many


def test_respects_weight_budget_and_runs_all():
    """Four weight-6 (armv7) scenarios under a budget of 6 must serialize: peak weight <= 6."""
    seen, inflight, peak = [], 0, 0

    async def run_one(s: Scenario) -> tuple[bool, str]:
        nonlocal inflight, peak
        inflight += s.weight()
        peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        inflight -= s.weight()
        seen.append(s.name)
        return True, "ok"

    scenarios = [Scenario(f"s{i}", Db.SQLITE, arch=Arch.ARMV7) for i in range(4)]  # weight 6 each
    results = asyncio.run(run_many(scenarios, concurrency_budget=6, run_one=run_one))
    assert len(results) == 4
    assert all(r.ok for r in results)
    assert {r.scenario.name for r in results} == {s.name for s in scenarios}
    assert peak <= 6  # never more than one armv7 (weight 6) at a time


def test_light_scenarios_run_concurrently_under_a_generous_budget():
    """Several weight-1 (amd64) scenarios under a budget that fits all of them run together."""
    inflight, peak = 0, 0

    async def run_one(s: Scenario) -> tuple[bool, str]:
        nonlocal inflight, peak
        inflight += s.weight()
        peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        inflight -= s.weight()
        return True, "ok"

    scenarios = [Scenario(f"s{i}", Db.SQLITE, arch=Arch.AMD64) for i in range(4)]  # weight 1 each
    results = asyncio.run(run_many(scenarios, concurrency_budget=4, run_one=run_one))
    assert len(results) == 4
    assert all(r.ok for r in results)
    # All four fit under the budget at once, so they should overlap: peak should reach 4,
    # not stay serialized at 1 -- this is what tells parallel execution apart from serial.
    assert peak == 4


def test_run_one_exception_becomes_a_failing_result_without_propagating():
    """A run_one that raises must not crash run_many -- it becomes a failing Result instead."""

    async def flaky(s: Scenario) -> tuple[bool, str]:
        if s.name == "boom":
            raise RuntimeError("kaboom")
        await asyncio.sleep(0.01)
        return True, "ok"

    scenarios = [
        Scenario("boom", Db.SQLITE, arch=Arch.AMD64),
        Scenario("fine", Db.SQLITE, arch=Arch.AMD64),
    ]
    results = asyncio.run(run_many(scenarios, concurrency_budget=2, run_one=flaky))
    by_name = {r.scenario.name: r for r in results}
    assert by_name["boom"].ok is False
    assert "kaboom" in by_name["boom"].detail
    assert by_name["fine"].ok is True


def test_run_many_admits_a_single_overweight_scenario_under_a_smaller_budget():
    """A lone weight-6 (armv7) scenario under concurrency_budget=4 must still complete.

    Guards the "admit when in_flight == 0 even if weight > budget" clause in `run_many`'s
    worker -- without it, a single armv7 scenario on a <6-core box (budget below 6) would
    `wait_for` forever, since `in_flight + weight <= concurrency_budget` (2 <= 4... wait, 6 <= 4)
    never holds. This is what `test-all` relies on to make progress on armv7 hardware with
    fewer than 6 cores.
    """

    async def run_one(_s: Scenario) -> tuple[bool, str]:
        await asyncio.sleep(0.01)
        return True, "ok"

    scenarios = [Scenario("armv7-solo", Db.SQLITE, arch=Arch.ARMV7)]  # weight 6
    results = asyncio.run(run_many(scenarios, concurrency_budget=4, run_one=run_one))
    assert len(results) == 1
    assert results[0].ok is True


@pytest.mark.parametrize("weight", [1, 4, 6])
def test_single_scenario_always_succeeds_regardless_of_weight(weight: int):
    """Sanity check across every arch weight: a lone scenario runs and reports ok."""
    arch = {1: Arch.AMD64, 4: Arch.ARM64, 6: Arch.ARMV7}[weight]

    async def run_one(_s: Scenario) -> tuple[bool, str]:
        return True, "ok"

    scenarios = [Scenario("solo", Db.SQLITE, arch=arch)]
    results = asyncio.run(run_many(scenarios, concurrency_budget=weight, run_one=run_one))
    assert len(results) == 1
    assert results[0].ok is True
