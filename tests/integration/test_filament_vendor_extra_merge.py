"""Integration tests for filament and vendor extra-field update semantics.

A PATCH of `extra` on a filament or vendor used to replace the whole set, while a spool's
merged per key (#233). The Svelte client saves one field at a time, so every save on a
filament or vendor wiped the entity's other extra fields (upstream issue 1141, reported
against this fork's v2026.8.3). Filament and vendor now merge per key like a spool, and a
null value clears a key — the backend half of upstream ae3208a9.
"""

import pytest
from httpx import AsyncClient

FIL = "/api/v1/filament"
VENDOR = "/api/v1/vendor"


async def _entity_with_fields(client: AsyncClient, entity: str) -> tuple[str, dict]:
    for key, name in [("slot", "Slot"), ("owner", "Owner")]:
        resp = await client.post(f"/api/v1/field/{entity}/{key}", json={"name": name, "field_type": "text"})
        assert resp.status_code == 200, resp.text
    if entity == "filament":
        body = {"density": 1.24, "diameter": 1.75, "extra": {"slot": '"3"', "owner": '"Sam"'}}
        base = FIL
    else:
        body = {"name": "Acme", "extra": {"slot": '"3"', "owner": '"Sam"'}}
        base = VENDOR
    resp = await client.post(base, json=body)
    assert resp.status_code == 200, resp.text
    return base, resp.json()


@pytest.mark.parametrize("entity", ["filament", "vendor"])
async def test_patching_one_key_keeps_the_others(client: AsyncClient, entity: str):
    base, item = await _entity_with_fields(client, entity)

    resp = await client.patch(f"{base}/{item['id']}", json={"extra": {"owner": '"Alex"'}})

    assert resp.status_code == 200, resp.text
    assert resp.json()["extra"] == {"slot": '"3"', "owner": '"Alex"'}
    fetched = await client.get(f"{base}/{item['id']}")
    assert fetched.json()["extra"] == {"slot": '"3"', "owner": '"Alex"'}


@pytest.mark.parametrize("entity", ["filament", "vendor"])
async def test_two_single_key_saves_keep_both_values(client: AsyncClient, entity: str):
    """The exact sequence the Svelte inspector's autosave produces."""
    base, item = await _entity_with_fields(client, entity)

    first = await client.patch(f"{base}/{item['id']}", json={"extra": {"slot": '"7"'}})
    second = await client.patch(f"{base}/{item['id']}", json={"extra": {"owner": '"Kim"'}})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["extra"] == {"slot": '"7"', "owner": '"Kim"'}


@pytest.mark.parametrize("entity", ["filament", "vendor"])
async def test_null_value_clears_the_key(client: AsyncClient, entity: str):
    base, item = await _entity_with_fields(client, entity)

    resp = await client.patch(f"{base}/{item['id']}", json={"extra": {"slot": None}})

    assert resp.status_code == 200, resp.text
    assert resp.json()["extra"] == {"owner": '"Sam"'}
    fetched = await client.get(f"{base}/{item['id']}")
    assert fetched.json()["extra"] == {"owner": '"Sam"'}


@pytest.mark.parametrize("entity", ["filament", "vendor"])
async def test_empty_extra_map_changes_nothing(client: AsyncClient, entity: str):
    base, item = await _entity_with_fields(client, entity)

    resp = await client.patch(f"{base}/{item['id']}", json={"extra": {}})

    assert resp.status_code == 200, resp.text
    assert resp.json()["extra"] == {"slot": '"3"', "owner": '"Sam"'}


@pytest.mark.parametrize("entity", ["filament", "vendor"])
async def test_clearing_an_unknown_key_is_rejected(client: AsyncClient, entity: str):
    base, item = await _entity_with_fields(client, entity)

    resp = await client.patch(f"{base}/{item['id']}", json={"extra": {"nope": None}})

    assert resp.status_code == 400, resp.text


@pytest.mark.parametrize("entity", ["filament", "vendor"])
async def test_null_on_create_is_rejected(client: AsyncClient, entity: str):
    """Create takes plain strings only; null is an update-time instruction."""
    for key in ("slot",):
        await client.post(f"/api/v1/field/{entity}/{key}", json={"name": "Slot", "field_type": "text"})
    body = {"extra": {"slot": None}}
    if entity == "filament":
        body |= {"density": 1.24, "diameter": 1.75}
    else:
        body |= {"name": "Acme"}

    resp = await client.post(FIL if entity == "filament" else VENDOR, json=body)

    assert resp.status_code in (400, 422), resp.text


@pytest.mark.parametrize("entity", ["filament", "vendor"])
async def test_null_extra_map_changes_nothing(client: AsyncClient, entity: str):
    """`"extra": null` used to be a 500 (iterating None); it now leaves extra alone."""
    base, item = await _entity_with_fields(client, entity)

    resp = await client.patch(f"{base}/{item['id']}", json={"extra": None, "comment": "x"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["extra"] == {"slot": '"3"', "owner": '"Sam"'}
    assert resp.json()["comment"] == "x"
