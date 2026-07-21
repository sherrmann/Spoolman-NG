"""Self-tests: nginx/traefik/caddy overlays proving the proxy axis end-to-end.

Each scenario keeps `spoolman` internal (no published port) and fronts it with a real proxy
sidecar. `wait_healthy` hits the health endpoint *through the proxy*, at the scenario's sub-path
(or root), which proves the proxy passes the base-path-aware app's routes through unchanged
(Spoolman mounts everything under `SPOOLMAN_BASE_PATH` and expects to receive that prefix, so a
prefix-stripping proxy config would 404).
"""
from __future__ import annotations

import shutil

import httpx
import pytest

from tests_scenarios import runner
from tests_scenarios.assertions import contract
from tests_scenarios.catalog import Db, Proxy, Scenario

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def test_nginx_subpath_serves_api_and_spa():
    s = Scenario("sqlite-nginx-subpath-selftest", Db.SQLITE, proxy=Proxy.NGINX, subpath="spoolman")
    stack = runner.bring_up(s)
    try:
        runner.wait_healthy(stack)  # hits <host>/spoolman/api/v1/health, through nginx
        contract.run(stack)
        # The SPA is served under the sub-path and config.js carries the base path:
        cfg = httpx.get(f"http://localhost:{stack.host_port}/spoolman/config.js", timeout=10)
        cfg.raise_for_status()
        assert "SPOOLMAN_BASE_PATH" in cfg.text
        assert "spoolman" in cfg.text
    finally:
        runner.tear_down(stack)


def test_traefik_root_serves_api():
    s = Scenario("sqlite-traefik-root-selftest", Db.SQLITE, proxy=Proxy.TRAEFIK)
    stack = runner.bring_up(s)
    try:
        runner.wait_healthy(stack)  # hits <host>/api/v1/health, through traefik
        contract.run(stack)
    finally:
        runner.tear_down(stack)


def test_caddy_subpath_serves_api():
    s = Scenario("sqlite-caddy-subpath-selftest", Db.SQLITE, proxy=Proxy.CADDY, subpath="spoolman")
    stack = runner.bring_up(s)
    try:
        runner.wait_healthy(stack)  # hits <host>/spoolman/api/v1/health, through caddy
        contract.run(stack)
        cfg = httpx.get(f"http://localhost:{stack.host_port}/spoolman/config.js", timeout=10)
        cfg.raise_for_status()
        assert "SPOOLMAN_BASE_PATH" in cfg.text
        assert "spoolman" in cfg.text
    finally:
        runner.tear_down(stack)
