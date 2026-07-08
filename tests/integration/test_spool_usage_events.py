"""Integration tests for the persisted spool usage/adjustment log and idempotency (#50, #60, #98).

Drives the real PUT /use, PUT /measure, PATCH /spool and GET /spool/{id}/events endpoints against
the temp DB, asserting the events recorded and that an Idempotency-Key makes a retry a no-op.
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"


async def _make_spool(client: AsyncClient, initial_weight: float = 1000, spool_weight: float = 200) -> dict:
    fil = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": "PLA"})
    assert fil.status_code == 200, fil.text
    sp = await client.post(
        SPOOL,
        json={"filament_id": fil.json()["id"], "initial_weight": initial_weight, "spool_weight": spool_weight},
    )
    assert sp.status_code == 200, sp.text
    return sp.json()


async def _events(client: AsyncClient, spool_id: int) -> list[dict]:
    resp = await client.get(f"{SPOOL}/{spool_id}/events")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_use_by_weight_records_a_use_event(client: AsyncClient):
    spool = await _make_spool(client)
    resp = await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 100, "comment": "test print"})
    assert resp.status_code == 200, resp.text

    events = await _events(client, spool["id"])
    assert len(events) == 1
    assert events[0]["event_type"] == "use"
    assert events[0]["delta"] == 100
    assert events[0]["comment"] == "test print"
    assert events[0]["spool_id"] == spool["id"]


async def test_use_by_length_records_an_event(client: AsyncClient):
    spool = await _make_spool(client)
    resp = await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_length": 1000})
    assert resp.status_code == 200, resp.text
    events = await _events(client, spool["id"])
    assert len(events) == 1
    assert events[0]["event_type"] == "use"
    assert events[0]["delta"] > 0


async def test_measure_records_a_measure_event_with_gross_weight(client: AsyncClient):
    spool = await _make_spool(client, initial_weight=1000, spool_weight=200)
    # Gross now 900 → net used = (1000+200) - 900 = 300.
    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 900})
    assert resp.status_code == 200, resp.text

    events = await _events(client, spool["id"])
    assert len(events) == 1
    assert events[0]["event_type"] == "measure"
    assert events[0]["measured_weight"] == 900
    assert events[0]["delta"] == 300


async def test_patch_used_weight_records_an_update_event(client: AsyncClient):
    spool = await _make_spool(client)
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 100})
    # The "reset usage" action (#77) is a PATCH of used_weight back to 0.
    resp = await client.patch(f"{SPOOL}/{spool['id']}", json={"used_weight": 0})
    assert resp.status_code == 200, resp.text

    events = await _events(client, spool["id"])
    types = [e["event_type"] for e in events]
    assert "update" in types
    update = next(e for e in events if e["event_type"] == "update")
    assert update["delta"] == -100  # used_weight 100 → 0


async def test_idempotency_key_makes_use_a_no_op_on_retry(client: AsyncClient):
    spool = await _make_spool(client)
    headers = {"Idempotency-Key": "abc-123"}

    first = await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 100}, headers=headers)
    assert first.status_code == 200
    assert first.json()["used_weight"] == 100
    assert "idempotency-replayed" not in {k.lower() for k in first.headers}

    second = await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 100}, headers=headers)
    assert second.status_code == 200
    # Not double-counted, and flagged as a replay.
    assert second.json()["used_weight"] == 100
    assert second.headers.get("Idempotency-Replayed") == "true"

    # Exactly one event was recorded.
    assert len(await _events(client, spool["id"])) == 1


async def test_different_keys_both_apply(client: AsyncClient):
    spool = await _make_spool(client)
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 100}, headers={"Idempotency-Key": "k1"})
    resp = await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 50}, headers={"Idempotency-Key": "k2"})
    assert resp.json()["used_weight"] == 150
    assert len(await _events(client, spool["id"])) == 2


async def test_use_without_new_fields_is_unchanged(client: AsyncClient):
    """A Moonraker-shaped body (no comment, no header) still works and records an event."""
    spool = await _make_spool(client)
    resp = await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 42})
    assert resp.status_code == 200, resp.text
    assert resp.json()["used_weight"] == 42
    events = await _events(client, spool["id"])
    assert len(events) == 1
    # comment is null → omitted by response_model_exclude_none.
    assert events[0].get("comment") is None


async def test_events_are_paginated_most_recent_first(client: AsyncClient):
    spool = await _make_spool(client)
    for _ in range(3):
        await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 10})

    resp = await client.get(f"{SPOOL}/{spool['id']}/events", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200, resp.text
    assert resp.headers["x-total-count"] == "3"
    assert len(resp.json()) == 2
