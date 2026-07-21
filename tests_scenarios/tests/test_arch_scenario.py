"""Self-test: an armv7 scenario builds (via buildx+QEMU) and boots for real.

Slow and heavily guarded -- this is the one self-test that actually compiles Python wheels
under emulation (see `runner.ensure_image`), so it is opt-in via `-m slow` rather than part of
the default fast suite.
"""
from __future__ import annotations

import shutil

import pytest

from tests_scenarios import runner
from tests_scenarios.assertions import contract
from tests_scenarios.catalog import Arch, Db, Scenario

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker+buildx required")


@pytest.mark.slow
def test_armv7_boots_and_serves():
    s = Scenario("armv7-sqlite-selftest", Db.SQLITE, arch=Arch.ARMV7)
    stack = runner.bring_up(s)
    try:
        runner.wait_healthy(stack, timeout=600)  # QEMU is slow
        contract.run(stack)  # health + one CRUD round-trip
    finally:
        runner.tear_down(stack)
