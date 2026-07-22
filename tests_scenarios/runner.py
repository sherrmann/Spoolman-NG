"""Lifecycle for a single scenario stack (docker-compose v1)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import httpx

from tests_scenarios import compose
from tests_scenarios.catalog import Arch, Auth, platform_for
from tests_scenarios.compose import REPO
from tests_scenarios.naming import free_port, project_name

if TYPE_CHECKING:
    from tests_scenarios.catalog import Scenario

__all__ = ["REPO", "ScenarioStack", "bring_up", "ensure_image", "provision_users", "tear_down", "wait_healthy"]

ENGINE = os.environ.get("SPOOLMAN_CONTAINER_ENGINE", "docker")
COMPOSE = [ENGINE + "-compose"] if ENGINE == "docker" else [ENGINE, "compose"]

AMD64_IMAGE = "spoolman:test"


def ensure_image(arch: Arch) -> str:
    """Return the image tag to run `arch` under, building it via buildx if it's missing.

    `Arch.AMD64` reuses the pre-built `spoolman:test` image unconditionally (never rebuilt here).
    Any other arch is tagged `spoolman:scn-<arch>`; if that tag isn't already present, this
    registers QEMU emulation (idempotent -- a fast no-op once already installed) and runs a
    `buildx --load` for just that one platform, so the harness is self-contained even on a host
    that has never built a foreign-arch image before.
    """
    if arch is Arch.AMD64:
        return AMD64_IMAGE
    tag = f"spoolman:scn-{arch}"
    if (
        subprocess.run(
            ["docker", "image", "inspect", tag],  # noqa: S607
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    ):
        return tag
    subprocess.run(
        ["docker", "run", "--privileged", "--rm", "tonistiigi/binfmt", "--install", "all"],  # noqa: S607
        check=True,
    )
    subprocess.run(
        ["docker", "buildx", "build", "--platform", platform_for(arch), "--load", "-t", tag, str(REPO)],  # noqa: S607
        check=True,
    )
    return tag


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

    Ensures the arch-appropriate server image exists first (see `ensure_image`) -- a no-op
    lookup for amd64, a cached-or-built buildx image for arm64/armv7 -- and points the rendered
    compose file's `spoolman` service at that tag.

    Self-cleaning on failure: if `up -d` fails partway through (e.g. one service starts
    but another fails), tear the partial project down and remove the temp compose file
    before re-raising, so callers never have to clean up a stack they never got back.
    """
    image = ensure_image(scenario.arch)
    host_port = free_port()
    project = project_name(scenario.name)
    compose_file = compose.render(scenario, host_port=host_port, project=project, image=image)
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


def provision_users(stack: ScenarioStack) -> None:
    """Bootstrap the scenario's login-flow admin account (no-op unless auth is ``Auth.USERS``).

    With ``SPOOLMAN_AUTH_SECRET`` set but zero user accounts, ``auth_required()`` is False (see
    ``spoolman/auth.py``), so requests -- including this one -- run as anonymous admin. That is
    what lets the very first account be created via an unauthenticated ``POST /auth/users``; every
    subsequent request requires real credentials. Idempotent: a 409 (user already exists) is
    treated as success, so callers can call this unconditionally after ``wait_healthy``.
    """
    if stack.scenario.auth is not Auth.USERS:
        return
    login = stack.scenario.test_env()["SPOOLMAN_TEST_LOGIN"]
    user, _, password = login.partition(":")
    resp = httpx.post(
        f"{stack.url}/api/v1/auth/users",
        json={"username": user, "password": password},
        timeout=10,
    )
    if resp.status_code != httpx.codes.CONFLICT:
        resp.raise_for_status()


def tear_down(stack: ScenarioStack) -> None:
    """Bring the stack down (volumes included) and remove its temp compose + proxy config files."""
    subprocess.run(_compose_cmd(stack.project, stack.compose_file, "down", "-v"), check=False)
    stack.compose_file.unlink(missing_ok=True)
    # compose.render (for proxy scenarios) writes "<project>-proxy.conf" alongside the compose
    # file; clean it up too, keyed off the project name since ScenarioStack doesn't track it.
    proxy_config = Path(tempfile.gettempdir()) / f"{stack.project}-proxy.conf"
    proxy_config.unlink(missing_ok=True)
