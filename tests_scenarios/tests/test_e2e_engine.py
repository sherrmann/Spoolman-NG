"""Fast, no-docker unit tests for the Playwright e2e env-building helper."""
from __future__ import annotations

from pathlib import Path

from tests_scenarios.assertions.e2e import _build_env
from tests_scenarios.catalog import Auth, Db, Scenario
from tests_scenarios.runner import ScenarioStack

_DUMMY_COMPOSE_FILE = Path("/dev/null")


def _dummy_stack(scenario: Scenario, *, host_port: int = 12345) -> ScenarioStack:
    url = f"http://localhost:{host_port}" + (f"/{scenario.subpath}" if scenario.subpath else "")
    return ScenarioStack(scenario, "dummy-project", host_port, url, _DUMMY_COMPOSE_FILE)


def test_build_env_no_proxy_no_auth() -> None:
    scenario = Scenario("sqlite-bare-e2e-unittest", Db.SQLITE)
    stack = _dummy_stack(scenario, host_port=12345)
    env = _build_env(stack)
    assert env["PLAYWRIGHT_TARGET_URL"] == "http://localhost:12345"
    assert env["PLAYWRIGHT_TARGET_BASE"] == ""
    assert "PLAYWRIGHT_TOKEN" not in env


def test_build_env_subpath_token_auth() -> None:
    scenario = Scenario(
        "postgres-auth-nginx-subpath-e2e-unittest", Db.POSTGRES, Auth.TOKEN, subpath="spoolman",
    )
    stack = _dummy_stack(scenario, host_port=23456)
    env = _build_env(stack)
    assert env["PLAYWRIGHT_TARGET_URL"] == "http://localhost:23456"
    assert env["PLAYWRIGHT_TARGET_BASE"] == "/spoolman"
    assert env["PLAYWRIGHT_TOKEN"] == scenario.test_env()["SPOOLMAN_TEST_TOKEN"]
