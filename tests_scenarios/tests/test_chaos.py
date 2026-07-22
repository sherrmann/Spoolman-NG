"""Chaos-engine selftests: kill -9 durability on sqlite, DB-outage recovery on postgres."""

from __future__ import annotations

import shutil

import pytest

from tests_scenarios import runner
from tests_scenarios.catalog import Db, Scenario

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def _run_chaos(scenario: Scenario) -> dict[str, str]:
    from tests_scenarios.assertions import chaos  # noqa: PLC0415 -- isolate the RED-phase ImportError here

    stack = runner.bring_up(scenario)
    try:
        runner.wait_healthy(stack)
        runner.provision_users(stack)
        return chaos.run(stack)
    finally:
        runner.tear_down(stack)


def test_sqlite_kill9_durability():
    results = _run_chaos(Scenario("chaos-sqlite-selftest", Db.SQLITE))
    assert "app-kill9" in results


def test_postgres_db_outage_recovery():
    results = _run_chaos(Scenario("chaos-postgres-selftest", Db.POSTGRES))
    assert "app-kill9" in results
    assert "db-outage" in results
