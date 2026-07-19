"""Integration tests for the Order / OrderLine entities (#298 Phase 1).

An order groups the lines of one bulk reorder. State (open/arrived) is derived from the lines, not
stored. A PATCH that includes `lines` fully replaces the line set; omitting it leaves lines alone.
Deleting an order cascades its lines; deleting a shop referenced by an order, or a filament
referenced by an order line, is restricted.
"""

from httpx import AsyncClient

ORDER = "/api/v1/order"
SHOP = "/api/v1/shop"
FIL = "/api/v1/filament"


async def _filament(client: AsyncClient, name: str = "PLA") -> int:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_order_crud_round_trip(client: AsyncClient):
    shop_id = (await client.post(SHOP, json={"name": "3DJake"})).json()["id"]
    fid = await _filament(client)

    created = (
        await client.post(
            ORDER,
            json={
                "shop_id": shop_id,
                "order_number": "4711",
                "lines": [{"filament_id": fid, "quantity": 2, "price_per_unit": 19.9}],
            },
        )
    ).json()
    assert created["shop"]["name"] == "3DJake"
    assert created["order_number"] == "4711"
    assert created["state"] == "open"
    assert len(created["lines"]) == 1
    assert created["lines"][0]["quantity"] == 2
    assert created["lines"][0]["price_per_unit"] == 19.9
    assert created["lines"][0].get("arrived_at") is None
    assert created["ordered_at"]  # defaulted to now
    order_id = created["id"]

    got = await client.get(f"{ORDER}/{order_id}")
    assert got.status_code == 200
    assert got.json()["state"] == "open"

    listed = await client.get(ORDER)
    assert listed.headers["x-total-count"] == "1"
    assert [o["id"] for o in listed.json()] == [order_id]


async def test_order_zero_lines_is_arrived_equivalent(client: AsyncClient):
    created = (await client.post(ORDER, json={"comment": "note only"})).json()
    assert created["lines"] == []
    assert created["state"] == "arrived"


async def test_patch_lines_full_replace(client: AsyncClient):
    fid_a = await _filament(client, "A")
    fid_b = await _filament(client, "B")
    order = (await client.post(ORDER, json={"lines": [{"filament_id": fid_a, "quantity": 1}]})).json()

    patched = await client.patch(
        f"{ORDER}/{order['id']}",
        json={"lines": [{"filament_id": fid_b, "quantity": 3}]},
    )
    assert patched.status_code == 200
    lines = patched.json()["lines"]
    assert len(lines) == 1
    assert lines[0]["filament_id"] == fid_b
    assert lines[0]["quantity"] == 3


async def test_patch_without_lines_leaves_them_untouched(client: AsyncClient):
    fid = await _filament(client)
    order = (await client.post(ORDER, json={"lines": [{"filament_id": fid, "quantity": 2}]})).json()
    patched = await client.patch(f"{ORDER}/{order['id']}", json={"comment": "updated"})
    assert patched.status_code == 200
    assert patched.json()["comment"] == "updated"
    assert len(patched.json()["lines"]) == 1


async def test_delete_order_cascades_lines(client: AsyncClient):
    fid = await _filament(client)
    order = (await client.post(ORDER, json={"lines": [{"filament_id": fid, "quantity": 2}]})).json()
    assert (await client.delete(f"{ORDER}/{order['id']}")).status_code == 200
    assert (await client.get(ORDER)).headers["x-total-count"] == "0"
    # The filament is now deletable — no order line references it anymore.
    assert (await client.delete(f"{FIL}/{fid}")).status_code == 200


async def test_delete_shop_restricted_while_order_references_it(client: AsyncClient):
    shop_id = (await client.post(SHOP, json={"name": "Locked"})).json()["id"]
    await client.post(ORDER, json={"shop_id": shop_id})
    blocked = await client.delete(f"{SHOP}/{shop_id}")
    assert blocked.status_code == 409, blocked.text


async def test_delete_filament_restricted_while_order_line_references_it(client: AsyncClient):
    fid = await _filament(client)
    await client.post(ORDER, json={"lines": [{"filament_id": fid, "quantity": 1}]})
    blocked = await client.delete(f"{FIL}/{fid}")
    assert blocked.status_code == 403, blocked.text
