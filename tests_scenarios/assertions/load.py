"""Load-smoke assertion engine: concurrent read-heavy mix with a write every 5th cycle.

Not a benchmark — a smoke: N async users hammer the list endpoints (plus a periodic
``PUT /spool/{id}/use``) for S seconds through whatever proxy/auth the scenario fronts.
Contract: zero transport errors, zero non-2xx responses, p95 latency under budget.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

from tests_scenarios.assertions.contract import _resolve_token

if TYPE_CHECKING:
    from tests_scenarios.runner import ScenarioStack

_MAX_ERRORS_SHOWN = 5


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile of `values` (any order); 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = math.ceil(q / 100 * len(ordered))
    return ordered[max(0, rank - 1)]


@dataclass
class LoadReport:
    """Outcome of one load run."""

    requests: int = 0
    errors: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    seconds: float = 0.0
    users: int = 0

    @property
    def rps(self) -> float:
        """Requests per second over the whole run."""
        return self.requests / self.seconds if self.seconds else 0.0

    @property
    def p50(self) -> float:
        """Median latency in ms."""
        return percentile(self.latencies_ms, 50)

    @property
    def p95(self) -> float:
        """95th-percentile latency in ms."""
        return percentile(self.latencies_ms, 95)

    @property
    def p99(self) -> float:
        """99th-percentile latency in ms."""
        return percentile(self.latencies_ms, 99)


def _seed(stack: ScenarioStack, headers: dict[str, str]) -> tuple[int, int, int]:
    """Create a vendor + filament + spool for the write mix; return their ids."""
    vendor = httpx.post(f"{stack.url}/api/v1/vendor", json={"name": "load-vendor"}, headers=headers, timeout=10)
    vendor.raise_for_status()
    filament = httpx.post(
        f"{stack.url}/api/v1/filament",
        json={
            "name": "load-fil",
            "material": "PLA",
            "density": 1.24,
            "diameter": 1.75,
            "weight": 1000,
            "vendor_id": vendor.json()["id"],
        },
        headers=headers,
        timeout=10,
    )
    filament.raise_for_status()
    spool = httpx.post(
        f"{stack.url}/api/v1/spool",
        json={"filament_id": filament.json()["id"], "initial_weight": 1000},
        headers=headers,
        timeout=10,
    )
    spool.raise_for_status()
    return vendor.json()["id"], filament.json()["id"], spool.json()["id"]


async def _worker(
    client: httpx.AsyncClient,
    stack: ScenarioStack,
    spool_id: int,
    deadline: float,
    report: LoadReport,
) -> None:
    cycle = 0
    while time.monotonic() < deadline:
        cycle += 1
        requests: list[tuple[str, str, dict | None]] = [
            ("GET", f"{stack.url}/api/v1/spool", None),
            ("GET", f"{stack.url}/api/v1/filament", None),
            ("GET", f"{stack.url}/api/v1/vendor", None),
        ]
        if cycle % 5 == 0:
            requests.append(("PUT", f"{stack.url}/api/v1/spool/{spool_id}/use", {"use_weight": 0.05}))
        for method, url, payload in requests:
            start = time.perf_counter()
            try:
                r = await client.request(method, url, json=payload)
            except httpx.HTTPError as e:
                report.errors.append(f"{method} {url}: {e}")
            else:
                report.latencies_ms.append((time.perf_counter() - start) * 1000)
                if not r.is_success:
                    report.errors.append(f"{method} {url}: HTTP {r.status_code}")
            report.requests += 1


async def _drive(stack: ScenarioStack, headers: dict[str, str], spool_id: int, report: LoadReport) -> None:
    deadline = time.monotonic() + report.seconds
    clients = [httpx.AsyncClient(headers=headers, timeout=10) for _ in range(report.users)]
    try:
        await asyncio.gather(*(_worker(c, stack, spool_id, deadline, report) for c in clients))
    finally:
        for c in clients:
            await c.aclose()


def run(stack: ScenarioStack, *, users: int = 10, seconds: int = 15, p95_budget_ms: int = 1500) -> LoadReport:
    """Run the load smoke against a live stack; raise AssertionError on errors or a blown budget."""
    token = _resolve_token(stack)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    vendor_id, filament_id, spool_id = _seed(stack, headers)

    report = LoadReport(seconds=seconds, users=users)
    started = time.monotonic()
    asyncio.run(_drive(stack, headers, spool_id, report))
    report.seconds = time.monotonic() - started

    for path in (f"spool/{spool_id}", f"filament/{filament_id}", f"vendor/{vendor_id}"):  # best-effort cleanup
        with contextlib.suppress(httpx.HTTPError):
            httpx.delete(f"{stack.url}/api/v1/{path}", headers=headers, timeout=10)

    if report.errors:
        shown = "\n  ".join(report.errors[:_MAX_ERRORS_SHOWN])
        raise AssertionError(f"{len(report.errors)} failed requests under load; first {_MAX_ERRORS_SHOWN}:\n  {shown}")
    if report.p95 > p95_budget_ms:
        msg = f"p95 latency {report.p95:.0f}ms exceeds budget {p95_budget_ms}ms (p50 {report.p50:.0f}ms)"
        raise AssertionError(msg)
    return report
