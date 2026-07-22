"""Self-test: `seed_sample` posts a deterministic dataset through the live API."""
from __future__ import annotations

import shutil

import httpx
import pytest

from tests_scenarios import runner
from tests_scenarios.catalog import Db, Scenario
from tests_scenarios.seed import seed_sample

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def test_seed_creates_expected_counts():
    stack = runner.bring_up(Scenario("sqlite-seed-selftest", Db.SQLITE))
    try:
        runner.wait_healthy(stack)
        counts = seed_sample(stack)
        assert counts["vendors"] >= 1
        assert counts["filaments"] >= 1
        assert counts["spools"] >= 1
        got = httpx.get(f"{stack.url}/api/v1/spool", timeout=10).json()
        assert len(got) == counts["spools"]
    finally:
        runner.tear_down(stack)
