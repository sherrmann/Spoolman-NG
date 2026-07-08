"""Integration tests for the spool `search` query param (issue #51).

Mirrors the filament search test: seed spools through the real POST endpoints, then drive
GET /spool?search=… and assert the returned rows. The search spans the spool's own comment,
lot number and location plus the linked filament's vendor/name/material/article number.
"""

import pytest
from httpx import AsyncClient

FIL = "/api/v1/filament"
VENDOR = "/api/v1/vendor"
SPOOL = "/api/v1/spool"


async def _search_ids(client: AsyncClient, query: str) -> set[int]:
    resp = await client.get(SPOOL, params={"search": query})
    assert resp.status_code == 200, resp.text
    return {s["id"] for s in resp.json()}


@pytest.fixture
async def seeded(client: AsyncClient) -> dict[str, int]:
    vendor = (await client.post(VENDOR, json={"name": "Prusa Research"})).json()
    pla = (
        await client.post(
            FIL,
            json={
                "density": 1.24,
                "diameter": 1.75,
                "name": "Galaxy Black",
                "material": "PLA",
                "vendor_id": vendor["id"],
            },
        )
    ).json()
    petg = (
        await client.post(FIL, json={"density": 1.27, "diameter": 1.75, "name": "Clear", "material": "PETG"})
    ).json()

    spool_a = (
        await client.post(SPOOL, json={"filament_id": pla["id"], "comment": "top shelf", "lot_nr": "LOT123"})
    ).json()
    spool_b = (await client.post(SPOOL, json={"filament_id": petg["id"], "location": "Drybox A"})).json()
    return {"a": spool_a["id"], "b": spool_b["id"]}


async def test_search_matches_linked_filament_fields(client: AsyncClient, seeded: dict[str, int]):
    assert await _search_ids(client, "galaxy") == {seeded["a"]}
    assert await _search_ids(client, "petg") == {seeded["b"]}
    assert await _search_ids(client, "prusa") == {seeded["a"]}


async def test_search_matches_spool_own_text(client: AsyncClient, seeded: dict[str, int]):
    assert await _search_ids(client, "top shelf") == {seeded["a"]}
    assert await _search_ids(client, "LOT123") == {seeded["a"]}
    assert await _search_ids(client, "drybox") == {seeded["b"]}


async def test_search_is_case_insensitive(client: AsyncClient, seeded: dict[str, int]):
    assert await _search_ids(client, "GALAXY") == {seeded["a"]}


async def test_comma_terms_are_ored(client: AsyncClient, seeded: dict[str, int]):
    assert await _search_ids(client, "galaxy,drybox") == {seeded["a"], seeded["b"]}


async def test_numeric_term_matches_spool_id(client: AsyncClient, seeded: dict[str, int]):
    assert await _search_ids(client, str(seeded["a"])) == {seeded["a"]}


async def test_empty_search_returns_everything(client: AsyncClient, seeded: dict[str, int]):
    assert await _search_ids(client, "") == {seeded["a"], seeded["b"]}


async def test_malformed_search_is_200_not_500(client: AsyncClient):
    resp = await client.get(SPOOL, params={"search": '"unterminated'})
    assert resp.status_code == 200, resp.text
