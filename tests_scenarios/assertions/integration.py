"""Run the existing tests_integration suite against a live scenario stack (from the host)."""
from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from tests_scenarios.runner import REPO

if TYPE_CHECKING:
    from tests_scenarios.runner import ScenarioStack


def run(stack: ScenarioStack, *, extra_pytest_args: tuple[str, ...] = ()) -> None:
    """Run `uv run pytest tests_integration/tests` against `stack`; raise on non-zero exit."""
    env = {**os.environ, "SPOOLMAN_TEST_URL": stack.url, **stack.scenario.test_env()}
    cmd = ["uv", "run", "pytest", "tests_integration/tests", "-q", *extra_pytest_args]
    result = subprocess.run(cmd, cwd=REPO, env=env, check=False)
    if result.returncode != 0:
        raise AssertionError(f"integration suite failed for {stack.scenario.name} (exit {result.returncode})")
