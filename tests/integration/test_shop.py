"""Integration tests for the Shop entity (#298 Phase 1).

A shop is where a reorder is placed: a unique name, an optional homepage, a free-form
list of regions it ships to (stored comma-separated, exposed as a JSON array), and a
comment. CRUD mirrors /vendor, plus a unique-name conflict and the ships_to array edge.
"""

from httpx import AsyncClient

SHOP = "/api/v1/shop"


async def test_shop_crud_round_trip(client: AsyncClient):
    created = (
        await client.post(
            SHOP,
            json={"name": "3DJake", "homepage": "https://3djake.com", "ships_to": ["CH", "EU"], "comment": "fast"},
        )
    ).json()
    assert created["name"] == "3DJake"
    assert created["homepage"] == "https://3djake.com"
    assert created["ships_to"] == ["CH", "EU"]
    assert created["comment"] == "fast"
    shop_id = created["id"]

    got = await client.get(f"{SHOP}/{shop_id}")
    assert got.status_code == 200
    assert got.json()["ships_to"] == ["CH", "EU"]

    listed = await client.get(SHOP)
    assert listed.status_code == 200
    assert listed.headers["x-total-count"] == "1"
    assert [s["name"] for s in listed.json()] == ["3DJake"]

    patched = await client.patch(f"{SHOP}/{shop_id}", json={"name": "3DJake DE", "ships_to": ["DE"]})
    assert patched.status_code == 200
    assert patched.json()["name"] == "3DJake DE"
    assert patched.json()["ships_to"] == ["DE"]

    deleted = await client.delete(f"{SHOP}/{shop_id}")
    assert deleted.status_code == 200
    empty = await client.get(SHOP)
    assert empty.headers["x-total-count"] == "0"
    assert empty.json() == []


async def test_shop_name_is_unique(client: AsyncClient):
    assert (await client.post(SHOP, json={"name": "Prusa"})).status_code == 200
    dup = await client.post(SHOP, json={"name": "Prusa"})
    assert dup.status_code == 409, dup.text


async def test_shop_ships_to_absent_when_unset(client: AsyncClient):
    created = (await client.post(SHOP, json={"name": "Bare"})).json()
    # response_model_exclude_none drops null ships_to entirely.
    assert "ships_to" not in created
    assert (await client.get(f"{SHOP}/{created['id']}")).json().get("ships_to") is None


async def test_shop_ships_to_empty_list_stored_as_null(client: AsyncClient):
    created = (await client.post(SHOP, json={"name": "Empty", "ships_to": []})).json()
    assert "ships_to" not in created
