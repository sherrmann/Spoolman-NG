"""Lifecycle for a single scenario stack (docker-compose v1)."""
from __future__ import annotations

import os
import subprocess
import time
from typing import TYPE_CHECKING, NamedTuple

import httpx

from tests_scenarios import compose
from tests_scenarios.compose import REPO
from tests_scenarios.naming import free_port, project_name

if TYPE_CHECKING:
    from pathlib import Path

    from tests_scenarios.catalog import Scenario

__all__ = ["REPO", "ScenarioStack", "bring_up", "tear_down", "wait_healthy"]

ENGINE = os.environ.get("SPOOLMAN_CONTAINER_ENGINE", "docker")
COMPOSE = [ENGINE + "-compose"] if ENGINE == "docker" else [ENGINE, "compose"]


class ScenarioStack(NamedTuple):
    """A running scenario deployment: where it lives and how to reach it."""

    scenario: Scenario
    project: str
    host_port: int
    url: str
    compose_file: Path


def _compose_cmd(project: str, compose_file: Path, *args: str) -> list[str]:
    return [*COMPOSE, "-p", project, "-f", str(compose_file), *args]


def bring_up(scenario: Scenario) -> ScenarioStack:
    """Render the compose file for `scenario` and bring the stack up in the background.

    Self-cleaning on failure: if `up -d` fails partway through (e.g. one service starts
    but another fails), tear the partial project down and remove the temp compose file
    before re-raising, so callers never have to clean up a stack they never got back.
    """
    host_port = free_port()
    project = project_name(scenario.name)
    compose_file = compose.render(scenario, host_port=host_port, project=project)
    url = f"http://localhost:{host_port}" + (f"/{scenario.subpath}" if scenario.subpath else "")
    stack = ScenarioStack(scenario, project, host_port, url, compose_file)
    try:
        subprocess.run(_compose_cmd(project, compose_file, "up", "-d"), check=True)
    except subprocess.CalledProcessError:
        tear_down(stack)
        raise
    return stack


def wait_healthy(stack: ScenarioStack, timeout: int = 180) -> None:
    """Poll the stack's health endpoint until it succeeds or `timeout` seconds elapse."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            r = httpx.get(f"{stack.url}/api/v1/health", timeout=2)
            if r.is_success:
                return
            last = f"{r.status_code} {r.text[:200]}"
        except httpx.HTTPError as e:
            last = str(e)
        time.sleep(1)
    raise TimeoutError(f"{stack.scenario.name} not healthy in {timeout}s: {last}")


def tear_down(stack: ScenarioStack) -> None:
    """Bring the stack down (volumes included) and remove its temp compose file."""
    subprocess.run(_compose_cmd(stack.project, stack.compose_file, "down", "-v"), check=False)
    stack.compose_file.unlink(missing_ok=True)
