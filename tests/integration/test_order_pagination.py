"""Reproduction for #319: /order pagination must not truncate joined lines.

find() eager-loads the one-to-many order lines (lazy=joined). Applying SQL
LIMIT/OFFSET directly over that join counts joined rows, so a limit can slice
through a boundary order's line set or return fewer than `limit` distinct orders.
"""

from httpx import AsyncClient

ORDER = "/api/v1/order"
FIL = "/api/v1/filament"


async def _filament(client: AsyncClient, name: str) -> int:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_limit_returns_distinct_orders_with_complete_lines(client: AsyncClient):
    # Three filaments so each order can carry several lines.
    fids = [await _filament(client, n) for n in ("A", "B", "C")]

    # Five orders, each with three lines.
    order_ids = []
    for _ in range(5):
        created = await client.post(
            ORDER,
            json={"lines": [{"filament_id": fid, "quantity": 1} for fid in fids]},
        )
        assert created.status_code == 200, created.text
        order_ids.append(created.json()["id"])

    # Ask for the first two orders, oldest first.
    resp = await client.get(ORDER, params={"limit": 2, "offset": 0, "sort": "id:asc"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Exactly `limit` distinct orders come back...
    assert len(body) == 2, f"expected 2 orders, got {len(body)}: {[o['id'] for o in body]}"
    assert [o["id"] for o in body] == order_ids[:2]
    # ...each with its full line set intact.
    for o in body:
        assert len(o["lines"]) == 3, f"order {o['id']} truncated to {len(o['lines'])} lines"

    # Total count reflects all matching orders, not joined rows.
    assert resp.headers["x-total-count"] == "5"


async def test_offset_paginates_over_distinct_orders(client: AsyncClient):
    fids = [await _filament(client, n) for n in ("A", "B", "C")]
    order_ids = []
    for _ in range(5):
        created = await client.post(
            ORDER,
            json={"lines": [{"filament_id": fid, "quantity": 1} for fid in fids]},
        )
        order_ids.append(created.json()["id"])

    seen = []
    for offset in range(0, 5, 2):
        resp = await client.get(ORDER, params={"limit": 2, "offset": offset, "sort": "id:asc"})
        assert resp.status_code == 200, resp.text
        for o in resp.json():
            assert len(o["lines"]) == 3, f"order {o['id']} truncated to {len(o['lines'])} lines"
            seen.append(o["id"])

    # Every order surfaced exactly once across the pages.
    assert seen == order_ids
