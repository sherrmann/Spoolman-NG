"""Run the existing tests_integration suite against a live scenario stack (from the host)."""
from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from tests_scenarios.catalog import Db
from tests_scenarios.runner import REPO

if TYPE_CHECKING:
    from tests_scenarios.runner import ScenarioStack

# tests_integration/tests/conftest.py's DbType enum values -- these are what DB_TYPE must
# be for get_db_type() to parse it. Our catalog.Db differs only for MariaDB (its DbType is
# "mysql", not "mariadb"), since that's the wire value Spoolman itself uses for that backend.
_DB_TYPE = {
    Db.SQLITE: "sqlite",
    Db.POSTGRES: "postgres",
    Db.MARIADB: "mysql",
    Db.COCKROACH: "cockroachdb",
}


def _build_env(stack: ScenarioStack) -> dict[str, str]:
    """Build the subprocess env for running tests_integration against `stack`.

    Includes ``DB_TYPE`` so host-run tests (like ``test_backup.py``) that call
    ``get_db_type()`` work the same as they do under the in-container harness, where
    ``DB_TYPE`` is normally set on the compose-internal ``tester`` service that the
    scenario harness's ``compose.render()`` drops (it asserts from the host instead).
    """
    return {
        **os.environ,
        "SPOOLMAN_TEST_URL": stack.url,
        "DB_TYPE": _DB_TYPE[stack.scenario.db],
        **stack.scenario.test_env(),
    }


def run(stack: ScenarioStack, *, extra_pytest_args: tuple[str, ...] = ()) -> None:
    """Run `uv run pytest tests_integration/tests` against `stack`; raise on non-zero exit."""
    env = _build_env(stack)
    cmd = ["uv", "run", "pytest", "tests_integration/tests", "-q", *extra_pytest_args]
    result = subprocess.run(cmd, cwd=REPO, env=env, check=False)
    if result.returncode != 0:
        raise AssertionError(f"integration suite failed for {stack.scenario.name} (exit {result.returncode})")
