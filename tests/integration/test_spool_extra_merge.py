"""Integration tests for spool extra-field update semantics (#233).

Maintainer decision on #233: spools deliberately MERGE partial extra updates (adopted from
an upstream PR so concurrent writers - e.g. the NFC flow and a user edit - can't clobber
each other's keys), unlike the other entities, which replace the whole set. That left keys
undeletable; a null value now removes the key. These tests pin all three behaviors.
"""

from httpx import AsyncClient

FIELD = "/api/v1/field/spool"
FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"


async def _spool_with_fields(client: AsyncClient) -> dict:
    for key, name in [("slot", "Slot"), ("owner", "Owner")]:
        resp = await client.post(f"{FIELD}/{key}", json={"name": name, "field_type": "text"})
        assert resp.status_code == 200, resp.text
    fil = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "weight": 1000})
    assert fil.status_code == 200, fil.text
    spool = await client.post(
        SPOOL,
        json={"filament_id": fil.json()["id"], "extra": {"slot": '"3"', "owner": '"Sam"'}},
    )
    assert spool.status_code == 200, spool.text
    return spool.json()


async def test_partial_extra_update_merges_and_keeps_other_keys(client: AsyncClient):
    spool = await _spool_with_fields(client)

    resp = await client.patch(f"{SPOOL}/{spool['id']}", json={"extra": {"owner": '"Alex"'}})

    assert resp.status_code == 200, resp.text
    assert resp.json()["extra"] == {"slot": '"3"', "owner": '"Alex"'}


async def test_null_value_removes_the_key(client: AsyncClient):
    spool = await _spool_with_fields(client)

    resp = await client.patch(f"{SPOOL}/{spool['id']}", json={"extra": {"slot": None}})

    assert resp.status_code == 200, resp.text
    assert resp.json()["extra"] == {"owner": '"Sam"'}
    fetched = await client.get(f"{SPOOL}/{spool['id']}")
    assert fetched.json()["extra"] == {"owner": '"Sam"'}


async def test_empty_extra_map_changes_nothing(client: AsyncClient):
    spool = await _spool_with_fields(client)

    resp = await client.patch(f"{SPOOL}/{spool['id']}", json={"extra": {}})

    assert resp.status_code == 200, resp.text
    assert resp.json()["extra"] == {"slot": '"3"', "owner": '"Sam"'}


async def test_deleting_an_unknown_key_is_rejected(client: AsyncClient):
    spool = await _spool_with_fields(client)

    resp = await client.patch(f"{SPOOL}/{spool['id']}", json={"extra": {"nope": None}})

    assert resp.status_code == 400, resp.text
