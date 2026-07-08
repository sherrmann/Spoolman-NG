"""Integration tests for the data import endpoint (issue #55).

Drives POST /api/v1/import/{entity} over the in-process harness: the create/upsert/skip modes, the
all-or-nothing transaction (a bad row commits nothing), dry-run, missing foreign keys, both body
formats, and a full export -> import round-trip that reuses the real /export output.
"""

import pytest
from httpx import AsyncClient

VENDOR = "/api/v1/vendor"
FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
IMPORT = "/api/v1/import"
EXPORT = "/api/v1/export"


async def _count(client: AsyncClient, resource: str) -> int:
    resp = await client.get(resource)
    assert resp.status_code == 200, resp.text
    return len(resp.json())


async def _import(client: AsyncClient, entity: str, body: str, **params: object) -> dict:
    resp = await client.post(f"{IMPORT}/{entity}", params=params, content=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_import_json_creates_vendors(client: AsyncClient):
    body = '[{"name": "Acme"}, {"name": "Globex", "comment": "hi"}]'
    result = await _import(client, "vendor", body, fmt="json", mode="create")
    assert result["created"] == 2
    assert result["errors"] == []
    assert await _count(client, VENDOR) == 2


async def test_import_csv_creates_vendors(client: AsyncClient):
    body = "name,comment\nAcme,first\nGlobex,second\n"
    result = await _import(client, "vendor", body, fmt="csv", mode="create")
    assert result["created"] == 2
    names = {v["name"] for v in (await client.get(VENDOR)).json()}
    assert names == {"Acme", "Globex"}


async def test_import_filament_links_existing_vendor(client: AsyncClient):
    vendor = (await client.post(VENDOR, json={"name": "Acme"})).json()
    body = f'[{{"name": "PLA", "density": 1.24, "diameter": 1.75, "vendor.id": {vendor["id"]}}}]'
    result = await _import(client, "filament", body, fmt="json", mode="create")
    assert result["created"] == 1
    filaments = (await client.get(FIL)).json()
    assert filaments[0]["vendor"]["id"] == vendor["id"]


async def test_import_missing_foreign_key_is_all_or_nothing(client: AsyncClient):
    body = '[{"name": "PLA", "density": 1.24, "diameter": 1.75, "vendor.id": 9999}]'
    result = await _import(client, "filament", body, fmt="json", mode="create")
    assert result["created"] == 0
    assert any("9999" in e for e in result["errors"])
    assert await _count(client, FIL) == 0


async def test_import_bad_row_rolls_back_the_whole_batch(client: AsyncClient):
    # Second row has no name (required) -> the whole import must be rejected, nothing committed.
    body = '[{"name": "Good"}, {"comment": "nameless"}]'
    result = await _import(client, "vendor", body, fmt="json", mode="create")
    assert result["created"] == 0
    assert len(result["errors"]) == 1
    assert await _count(client, VENDOR) == 0


async def test_dry_run_reports_counts_without_committing(client: AsyncClient):
    body = '[{"name": "Acme"}, {"name": "Globex"}]'
    result = await _import(client, "vendor", body, fmt="json", mode="create", dry_run=True)
    assert result["created"] == 2
    assert result["dry_run"] is True
    assert await _count(client, VENDOR) == 0


async def test_upsert_updates_existing_and_inserts_new(client: AsyncClient):
    existing = (await client.post(VENDOR, json={"name": "Original"})).json()
    body = f'[{{"id": {existing["id"]}, "name": "Renamed"}}, {{"name": "Brand New"}}]'
    result = await _import(client, "vendor", body, fmt="json", mode="upsert")
    assert result["updated"] == 1
    assert result["created"] == 1
    refreshed = (await client.get(f"{VENDOR}/{existing['id']}")).json()
    assert refreshed["name"] == "Renamed"


async def test_skip_existing_leaves_existing_untouched(client: AsyncClient):
    existing = (await client.post(VENDOR, json={"name": "Original"})).json()
    body = f'[{{"id": {existing["id"]}, "name": "Should Not Apply"}}, {{"name": "Fresh"}}]'
    result = await _import(client, "vendor", body, fmt="json", mode="skip_existing")
    assert result["skipped"] == 1
    assert result["created"] == 1
    refreshed = (await client.get(f"{VENDOR}/{existing['id']}")).json()
    assert refreshed["name"] == "Original"


async def test_create_mode_ignores_id_and_always_inserts(client: AsyncClient):
    existing = (await client.post(VENDOR, json={"name": "Original"})).json()
    body = f'[{{"id": {existing["id"]}, "name": "Copy"}}]'
    result = await _import(client, "vendor", body, fmt="json", mode="create")
    assert result["created"] == 1
    assert result["updated"] == 0
    # Original still present, plus the new copy.
    assert await _count(client, VENDOR) == 2


async def test_unknown_entity_is_reported_not_crashed(client: AsyncClient):
    result = await _import(client, "widget", "[]", fmt="json", mode="create")
    assert result["created"] == 0
    assert any("widget" in e for e in result["errors"])


async def test_export_then_import_roundtrip_preserves_spool(client: AsyncClient):
    # Build vendor -> filament -> spool, consume some, then export all three and re-import via upsert.
    vendor = (await client.post(VENDOR, json={"name": "Acme", "empty_spool_weight": 200})).json()
    filament = (
        await client.post(
            FIL,
            json={"name": "PLA", "density": 1.24, "diameter": 1.75, "weight": 1000, "vendor_id": vendor["id"]},
        )
    ).json()
    spool = (await client.post(SPOOL, json={"filament_id": filament["id"], "initial_weight": 1000})).json()
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 250})

    before = (await client.get(f"{SPOOL}/{spool['id']}")).json()

    # Export each level as JSON and re-import with upsert (ids are preserved in the same DB).
    for entity in ("vendors", "filaments", "spools"):
        exported = (await client.get(f"{EXPORT}/{entity}", params={"fmt": "json"})).text
        singular = entity[:-1]
        result = await _import(client, singular, exported, fmt="json", mode="upsert")
        assert result["errors"] == [], f"{entity}: {result['errors']}"
        assert result["updated"] >= 1

    after = (await client.get(f"{SPOOL}/{spool['id']}")).json()
    assert after["used_weight"] == pytest.approx(before["used_weight"])
    assert after["remaining_weight"] == pytest.approx(before["remaining_weight"])
    assert after["filament"]["id"] == filament["id"]
    # No duplicate rows were created by the round-trip.
    assert await _count(client, VENDOR) == 1
    assert await _count(client, FIL) == 1
