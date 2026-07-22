"""Drive Playwright's target-external mode against a live scenario stack."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from tests_scenarios.runner import REPO

if TYPE_CHECKING:
    from tests_scenarios.runner import ScenarioStack


def _build_env(stack: ScenarioStack) -> dict[str, str]:
    """Build the subprocess env for running `client/e2e/external.spec.ts` against `stack`.

    Uses ``http://localhost:<host_port>`` (not ``stack.url``) as the origin, since
    ``external.spec.ts`` appends the base path itself via ``PLAYWRIGHT_TARGET_BASE``.
    """
    origin = f"http://localhost:{stack.host_port}"
    base = f"/{stack.scenario.subpath}" if stack.scenario.subpath else ""
    env = {**os.environ, "PLAYWRIGHT_TARGET_URL": origin, "PLAYWRIGHT_TARGET_BASE": base}
    token = stack.scenario.test_env().get("SPOOLMAN_TEST_TOKEN")
    if token:
        env["PLAYWRIGHT_TOKEN"] = token
    return env


def run(stack: ScenarioStack) -> None:
    """Run `npx playwright test` (external mode) against `stack`; raise on non-zero exit."""
    env = _build_env(stack)
    cmd = ["npx", "playwright", "test"]
    result = subprocess.run(cmd, cwd=REPO / "client", env=env, check=False)
    if result.returncode != 0:
        raise AssertionError(f"Playwright e2e failed for {stack.scenario.name} (exit {result.returncode})")
