"""Integration tests for the persisted SpoolmanDB catalog fields on filaments (issue #91 / #567).

spool_type, finish, pattern, translucent and glow live in the external catalog but used to be
dropped the moment a filament was imported locally. These drive the real POST/GET/PATCH endpoints
and assert the fields round-trip, that the enum fields reject unknown values, and that they stay
absent (never defaulted) when unset so existing integrations see an unchanged payload.
"""

import pytest
from httpx import AsyncClient

API = "/api/v1/filament"


async def _add_filament(client: AsyncClient, **fields: object) -> dict:
    body = {"density": 1.24, "diameter": 1.75, **fields}
    resp = await client.post(API, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_catalog_fields_round_trip_on_create_and_get(client: AsyncClient):
    filament = await _add_filament(
        client,
        spool_type="cardboard",
        finish="matte",
        pattern="sparkle",
        translucent=False,
        glow=True,
    )
    assert filament["spool_type"] == "cardboard"
    assert filament["finish"] == "matte"
    assert filament["pattern"] == "sparkle"
    assert filament["translucent"] is False
    assert filament["glow"] is True

    got = await client.get(f"{API}/{filament['id']}")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["spool_type"] == "cardboard"
    assert body["glow"] is True
    # A False boolean must survive (distinct from unset) rather than being dropped as falsy.
    assert body["translucent"] is False


async def test_catalog_fields_absent_when_unset(client: AsyncClient):
    # Additive: a plain filament must not gain any of the new fields, so existing consumers
    # (Moonraker/OctoPrint/HA) see a byte-identical payload.
    filament = await _add_filament(client)
    for key in ("spool_type", "finish", "pattern", "translucent", "glow"):
        assert key not in filament, key


async def test_catalog_fields_can_be_patched_and_cleared(client: AsyncClient):
    filament = await _add_filament(client)
    fid = filament["id"]

    patched = await client.patch(f"{API}/{fid}", json={"spool_type": "metal", "glow": True})
    assert patched.status_code == 200, patched.text
    assert patched.json()["spool_type"] == "metal"
    assert patched.json()["glow"] is True

    cleared = await client.patch(f"{API}/{fid}", json={"spool_type": None})
    assert cleared.status_code == 200, cleared.text
    assert "spool_type" not in cleared.json()
    # The other field is untouched by the partial update.
    assert cleared.json()["glow"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [("spool_type", "wooden"), ("finish", "shiny"), ("pattern", "stripes")],
)
async def test_unknown_enum_value_is_rejected(client: AsyncClient, field: str, value: str):
    resp = await client.post(API, json={"density": 1.24, "diameter": 1.75, field: value})
    assert resp.status_code == 422, resp.text
