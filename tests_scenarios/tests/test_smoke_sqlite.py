"""End-to-end smoke test: bring up sqlite-bare, run the contract, tear down."""
from __future__ import annotations

import shutil

import pytest

from tests_scenarios import runner
from tests_scenarios.assertions import contract
from tests_scenarios.catalog import Db, Scenario

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def test_sqlite_bare_up_contract_down():
    scenario = Scenario("sqlite-bare-selftest", Db.SQLITE)
    stack = runner.bring_up(scenario)
    try:
        runner.wait_healthy(stack)
        contract.run(stack)  # health + one CRUD round-trip
    finally:
        runner.tear_down(stack)
