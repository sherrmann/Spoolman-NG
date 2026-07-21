"""Fast, no-docker unit tests for the integration-suite env-building helper."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests_scenarios.assertions.integration import _build_env
from tests_scenarios.catalog import Db, Scenario
from tests_scenarios.runner import ScenarioStack

_DUMMY_COMPOSE_FILE = Path("/dev/null")


def _dummy_stack(db: Db) -> ScenarioStack:
    scenario = Scenario(f"{db}-engine-unittest", db)
    return ScenarioStack(scenario, "dummy-project", 12345, "http://localhost:12345", _DUMMY_COMPOSE_FILE)


@pytest.mark.parametrize(
    ("db", "expected_db_type"),
    [
        (Db.SQLITE, "sqlite"),
        (Db.POSTGRES, "postgres"),
        (Db.MARIADB, "mysql"),
        (Db.COCKROACH, "cockroachdb"),
    ],
)
def test_build_env_maps_db_type(db: Db, expected_db_type: str) -> None:
    stack = _dummy_stack(db)
    env = _build_env(stack)
    assert env["DB_TYPE"] == expected_db_type
    assert env["SPOOLMAN_TEST_URL"] == stack.url
