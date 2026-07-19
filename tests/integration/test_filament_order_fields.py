"""Integration tests for the filament 'ordered' state (#298).

Low-stock filament that has already been reordered gets three nullable fields:
ordered_at (doubles as the boolean and the age of the order), order_url (the
shop/bulk-order link) and order_note (order number, quantity, supplier). All
additive: absent until set, settable at create or via PATCH, cleared with null —
so existing integrations and the wire format are unaffected.
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"

STAMP = "2026-07-19T09:00:00Z"
URL = "https://shop.example.com/order/4711"
NOTE = "3 spools, order #4711"


async def _make_filament(client: AsyncClient, **extra: str) -> dict:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": "PLA", **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_new_filament_has_no_order_fields(client: AsyncClient):
    fil = await _make_filament(client)
    # Absent until set (null → omitted by response_model_exclude_none).
    assert fil.get("ordered_at") is None
    assert fil.get("order_url") is None
    assert fil.get("order_note") is None


async def test_create_with_order_fields(client: AsyncClient):
    # Ordering can precede owning: a filament created for an order carries the state from birth.
    fil = await _make_filament(client, ordered_at=STAMP, order_url=URL, order_note=NOTE)
    assert fil["ordered_at"] == STAMP
    assert fil["order_url"] == URL
    assert fil["order_note"] == NOTE


async def test_patch_marks_filament_ordered(client: AsyncClient):
    fil = await _make_filament(client)
    resp = await client.patch(f"{FIL}/{fil['id']}", json={"ordered_at": STAMP, "order_url": URL, "order_note": NOTE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ordered_at"] == STAMP
    assert body["order_url"] == URL
    assert body["order_note"] == NOTE

    got = await client.get(f"{FIL}/{fil['id']}")
    assert got.json()["ordered_at"] == STAMP
    assert got.json()["order_url"] == URL


async def test_patch_null_clears_order_fields(client: AsyncClient):
    fil = await _make_filament(client, ordered_at=STAMP, order_url=URL, order_note=NOTE)
    resp = await client.patch(f"{FIL}/{fil['id']}", json={"ordered_at": None, "order_url": None, "order_note": None})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("ordered_at") is None
    assert body.get("order_url") is None
    assert body.get("order_note") is None


async def test_patch_other_fields_leaves_order_state_untouched(client: AsyncClient):
    # exclude_unset semantics: a PATCH that doesn't mention the order fields must not clear them.
    fil = await _make_filament(client, ordered_at=STAMP, order_url=URL)
    resp = await client.patch(f"{FIL}/{fil['id']}", json={"name": "PLA v2"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["ordered_at"] == STAMP
    assert resp.json()["order_url"] == URL
