"""Chaos assertions: acknowledged-write durability across kill -9, and DB-outage recovery.

Contract 1 (every scenario): any write the API acknowledged with a 2xx must still exist
after the app container is SIGKILLed mid-write-storm and restarted.
Contract 2 (scenarios with a db service): after the DB container is SIGKILLed and
restarted, the app must serve successful writes again within 60s without being restarted
itself.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
import time
from typing import TYPE_CHECKING

import httpx

from tests_scenarios.assertions.contract import _resolve_token
from tests_scenarios.catalog import Db

if TYPE_CHECKING:
    from tests_scenarios.runner import ScenarioStack

_RECOVERY_TIMEOUT = 60


def _compose(stack: ScenarioStack, *args: str) -> None:
    from tests_scenarios import runner  # noqa: PLC0415 -- mirrors the harness's lazy-docker-import convention

    subprocess.run(
        [*runner.COMPOSE, "-p", stack.project, "-f", str(stack.compose_file), *args],
        check=True,
    )


def _write_storm(stack: ScenarioStack, headers: dict[str, str], stop: threading.Event, confirmed: list[int]) -> None:
    i = 0
    while not stop.is_set():
        i += 1
        try:
            r = httpx.post(f"{stack.url}/api/v1/vendor", json={"name": f"chaos-{i}"}, headers=headers, timeout=5)
        except httpx.HTTPError:
            return  # the app just died under us; only acknowledged writes matter
        if r.is_success:
            confirmed.append(r.json()["id"])


def run(stack: ScenarioStack, *, write_seconds: float = 2.0) -> dict[str, str]:
    """Run the chaos contracts against a live stack; raise AssertionError on violation."""
    token = _resolve_token(stack)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    results: dict[str, str] = {}
    confirmed: list[int] = []
    stop = threading.Event()

    writer = threading.Thread(target=_write_storm, args=(stack, headers, stop, confirmed))
    writer.start()
    time.sleep(write_seconds)
    _compose(stack, "kill", "-s", "SIGKILL", "spoolman")
    stop.set()
    writer.join(timeout=10)
    if not confirmed:
        raise AssertionError("no writes were acknowledged before the kill; nothing to verify")

    _compose(stack, "up", "-d")
    from tests_scenarios import runner  # noqa: PLC0415 -- mirrors the harness's lazy-docker-import convention

    runner.wait_healthy(stack)
    missing = [
        vid
        for vid in confirmed
        if httpx.get(f"{stack.url}/api/v1/vendor/{vid}", headers=headers, timeout=10).status_code != httpx.codes.OK
    ]
    if missing:
        raise AssertionError(f"kill -9 lost {len(missing)}/{len(confirmed)} acknowledged writes: ids {missing}")
    results["app-kill9"] = f"{len(confirmed)} acknowledged writes survived SIGKILL + restart"

    if stack.scenario.db is not Db.SQLITE:
        _compose(stack, "kill", "-s", "SIGKILL", "db")
        _compose(stack, "up", "-d")
        deadline = time.time() + _RECOVERY_TIMEOUT
        last = ""
        while time.time() < deadline:
            try:
                r = httpx.post(
                    f"{stack.url}/api/v1/vendor", json={"name": "chaos-db-recovery"}, headers=headers, timeout=5
                )
                if r.is_success:
                    confirmed.append(r.json()["id"])
                    break
                last = f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last = str(e)
            time.sleep(1)
        else:
            raise AssertionError(f"app did not serve writes within {_RECOVERY_TIMEOUT}s of the DB restart: {last}")
        results["db-outage"] = "app reconnected and served writes after DB SIGKILL + restart"

    for vid in confirmed:  # best-effort cleanup
        with contextlib.suppress(httpx.HTTPError):
            httpx.delete(f"{stack.url}/api/v1/vendor/{vid}", headers=headers, timeout=5)
    return results
