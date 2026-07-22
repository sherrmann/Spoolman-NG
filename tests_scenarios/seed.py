"""Deterministic sample-data seeding for manually-inspected scenarios.

``seed_sample`` posts a fixed, small dataset through the public API (honoring whatever auth
the scenario requires) so `poe scenario up <name>` for a `seed=True` scenario leaves behind a
stack with realistic-looking data instead of an empty database.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from tests_scenarios.catalog import Auth

if TYPE_CHECKING:
    from tests_scenarios.runner import ScenarioStack

_VENDOR = {"name": "Seed Filaments Co."}
_FILAMENTS = (
    {"name": "Galaxy Black", "material": "PLA", "density": 1.24, "diameter": 1.75},
    {"name": "Ocean Blue", "material": "PETG", "density": 1.27, "diameter": 1.75},
)
_SPOOLS_PER_FILAMENT = (2, 1)  # 2 spools of the first filament, 1 of the second -> 3 total


def _resolve_token(stack: ScenarioStack) -> str | None:
    """Resolve the bearer token for `stack`, mirroring `assertions.contract._resolve_token`.

    Static token if the scenario is `Auth.TOKEN`; a fresh login token if it's `Auth.USERS`;
    `None` (no auth header) otherwise. Kept local/duplicated rather than importing from
    `contract.py` so seeding has no dependency on the assertion suites.
    """
    tenv = stack.scenario.test_env()
    token = tenv.get("SPOOLMAN_TEST_TOKEN")
    if token:
        return token
    if stack.scenario.auth is Auth.USERS:
        user, _, password = tenv["SPOOLMAN_TEST_LOGIN"].partition(":")
        resp = httpx.post(
            f"{stack.url}/api/v1/auth/login",
            json={"username": user, "password": password},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    return None


def seed_sample(stack: ScenarioStack) -> dict[str, int]:
    """Post a fixed sample dataset (1 vendor -> 2 filaments -> 3 spools) through the API.

    Uses whatever auth `stack.scenario` requires (static token, login token, or none), so it
    exercises the write path under the scenario's real auth+proxy setup. Returns the number of
    each resource actually created, for callers (and tests) to assert against.
    """
    token = _resolve_token(stack)
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    vendor = httpx.post(f"{stack.url}/api/v1/vendor", json=_VENDOR, headers=headers, timeout=10)
    vendor.raise_for_status()
    vendor_id = vendor.json()["id"]

    filament_ids: list[int] = []
    for payload in _FILAMENTS:
        filament = httpx.post(
            f"{stack.url}/api/v1/filament",
            json={**payload, "vendor_id": vendor_id},
            headers=headers,
            timeout=10,
        )
        filament.raise_for_status()
        filament_ids.append(filament.json()["id"])

    spool_count = 0
    for filament_id, count in zip(filament_ids, _SPOOLS_PER_FILAMENT, strict=True):
        for _ in range(count):
            spool = httpx.post(
                f"{stack.url}/api/v1/spool",
                json={"filament_id": filament_id},
                headers=headers,
                timeout=10,
            )
            spool.raise_for_status()
            spool_count += 1

    return {"vendors": 1, "filaments": len(filament_ids), "spools": spool_count}
