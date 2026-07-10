"""Integration tests for the spool `archived` query param.

The client's "Show Archived" view needs an archived-only list; `allow_archived` alone can
only widen the default active-only view to a mixed one. `archived=true` narrows to archived
spools, `archived=false` to active ones, and either overrides `allow_archived`.
"""

import pytest
from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"


async def _find_ids(client: AsyncClient, **params: str) -> set[int]:
    resp = await client.get(SPOOL, params=params)
    assert resp.status_code == 200, resp.text
    return {s["id"] for s in resp.json()}


@pytest.fixture
async def seeded(client: AsyncClient) -> dict[str, int]:
    fil = (await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": "Archive PLA"})).json()
    active = (await client.post(SPOOL, json={"filament_id": fil["id"]})).json()
    archived = (await client.post(SPOOL, json={"filament_id": fil["id"], "archived": True})).json()
    return {"active": active["id"], "archived": archived["id"]}


async def test_default_lists_only_active(client: AsyncClient, seeded: dict[str, int]):
    assert await _find_ids(client) == {seeded["active"]}


async def test_allow_archived_lists_both(client: AsyncClient, seeded: dict[str, int]):
    assert await _find_ids(client, allow_archived="true") == {seeded["active"], seeded["archived"]}


async def test_archived_true_lists_only_archived(client: AsyncClient, seeded: dict[str, int]):
    assert await _find_ids(client, archived="true") == {seeded["archived"]}


async def test_archived_false_overrides_allow_archived(client: AsyncClient, seeded: dict[str, int]):
    assert await _find_ids(client, archived="false", allow_archived="true") == {seeded["active"]}


async def test_archived_true_respects_other_filters(client: AsyncClient, seeded: dict[str, int]):
    # Combine with a location filter that matches nothing: the archived narrowing must
    # intersect with (not replace) the other criteria.
    assert seeded["archived"] in await _find_ids(client, archived="true")
    assert await _find_ids(client, archived="true", location="Nowhere") == set()
