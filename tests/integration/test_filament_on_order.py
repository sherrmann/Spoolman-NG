"""Integration tests for the filament on_order computed field (#298 Phase 1).

on_order is the oldest OPEN order (an order with an un-arrived line) containing the filament, as
{order_id, ordered_at}; null when nothing of the filament is outstanding. It is populated only on the
filament list and detail endpoints (like spool_count), and clears when the line arrives.
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
ORDER = "/api/v1/order"


async def _filament(client: AsyncClient, name: str = "PLA") -> int:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_no_order_means_no_on_order(client: AsyncClient):
    fid = await _filament(client)
    assert "on_order" not in (await client.get(f"{FIL}/{fid}")).json()  # excluded when null
    assert "on_order" not in (await client.get(FIL)).json()[0]


async def test_open_order_sets_on_order(client: AsyncClient):
    fid = await _filament(client)
    order = (await client.post(ORDER, json={"lines": [{"filament_id": fid, "quantity": 1}]})).json()

    detail = (await client.get(f"{FIL}/{fid}")).json()
    assert detail["on_order"]["order_id"] == order["id"]
    assert detail["on_order"]["ordered_at"] == order["ordered_at"]

    listed = (await client.get(FIL)).json()
    assert listed[0]["on_order"]["order_id"] == order["id"]


async def test_oldest_open_order_wins(client: AsyncClient):
    fid = await _filament(client)
    older = (
        await client.post(
            ORDER, json={"ordered_at": "2026-01-01T00:00:00Z", "lines": [{"filament_id": fid, "quantity": 1}]}
        )
    ).json()
    await client.post(
        ORDER,
        json={"ordered_at": "2026-06-01T00:00:00Z", "lines": [{"filament_id": fid, "quantity": 1}]},
    )
    assert (await client.get(f"{FIL}/{fid}")).json()["on_order"]["order_id"] == older["id"]


async def test_on_order_clears_when_line_arrives(client: AsyncClient):
    fid = await _filament(client)
    order = (await client.post(ORDER, json={"lines": [{"filament_id": fid, "quantity": 1}]})).json()
    assert (await client.get(f"{FIL}/{fid}")).json()["on_order"]["order_id"] == order["id"]

    await client.post(f"{ORDER}/{order['id']}/arrive", json={"create_spools": False})
    assert "on_order" not in (await client.get(f"{FIL}/{fid}")).json()
