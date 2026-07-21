"""Lean deployment contract: health + one CRUD round-trip + (if auth) reject-without-token."""
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from tests_scenarios.catalog import Auth

if TYPE_CHECKING:
    from tests_scenarios.runner import ScenarioStack


def run(stack: ScenarioStack) -> None:
    """Run the lean deployment contract against a live `stack`; raise on any failed check."""
    tenv = stack.scenario.test_env()
    token = tenv.get("SPOOLMAN_TEST_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    httpx.get(f"{stack.url}/api/v1/health", timeout=10).raise_for_status()

    if stack.scenario.auth is Auth.TOKEN:
        anon = httpx.get(f"{stack.url}/api/v1/vendor", timeout=10)
        if anon.status_code not in (401, 403):
            raise AssertionError(f"auth not enforced: anon vendor list => {anon.status_code}")

    created = httpx.post(f"{stack.url}/api/v1/vendor", json={"name": "contract-vendor"},
                          headers=headers, timeout=10)
    created.raise_for_status()
    vid = created.json()["id"]
    got = httpx.get(f"{stack.url}/api/v1/vendor/{vid}", headers=headers, timeout=10)
    got.raise_for_status()
    if got.json()["name"] != "contract-vendor":
        raise AssertionError("CRUD round-trip mismatch")
    httpx.delete(f"{stack.url}/api/v1/vendor/{vid}", headers=headers, timeout=10).raise_for_status()
