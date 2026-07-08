"""Integration tests for the per-filament / per-vendor stock aggregates (B5: #49, #53, #109, #116).

Seeds filaments, spools and vendors through the real POST endpoints, then asserts the aggregate
fields returned by GET /filament, GET /filament/{id}, GET /vendor and GET /vendor/{id}:
  - spool_count / remaining_weight per filament (non-archived spools only),
  - filament_count / spool_count per vendor,
  - server-side sort by the filament aggregates,
  - low_stock_threshold / reserve_count round-trip,
and guards that these aggregates never leak into the nested spool.filament payload (compat: the
Moonraker/HA read shape must not grow required fields).
"""

import pytest
from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
VENDOR = "/api/v1/vendor"


async def _add_filament(client: AsyncClient, **fields: object) -> dict:
    body = {"density": 1.24, "diameter": 1.75, **fields}
    resp = await client.post(FIL, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _add_spool(client: AsyncClient, filament_id: int, **fields: object) -> dict:
    resp = await client.post(SPOOL, json={"filament_id": filament_id, **fields})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _use(client: AsyncClient, spool_id: int, weight: float) -> dict:
    resp = await client.put(f"{SPOOL}/{spool_id}/use", json={"use_weight": weight})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _get_filament(client: AsyncClient, filament_id: int) -> dict:
    resp = await client.get(f"{FIL}/{filament_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _list_filaments(client: AsyncClient, **params: object) -> list[dict]:
    resp = await client.get(FIL, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_spool_count_and_remaining_weight_sum_across_spools(client: AsyncClient):
    fil = await _add_filament(client, name="PLA", weight=1000)
    a = await _add_spool(client, fil["id"], initial_weight=1000)
    b = await _add_spool(client, fil["id"], initial_weight=1000)
    c = await _add_spool(client, fil["id"], initial_weight=1000)
    await _use(client, a["id"], 100)
    await _use(client, b["id"], 200)
    await _use(client, c["id"], 300)

    got = await _get_filament(client, fil["id"])
    assert got["spool_count"] == 3
    # 900 + 800 + 700, matching each spool's own clamped remaining weight.
    assert got["remaining_weight"] == pytest.approx(2400)


async def test_archived_spool_excluded_from_aggregates(client: AsyncClient):
    fil = await _add_filament(client, name="PETG", weight=1000)
    keep = await _add_spool(client, fil["id"], initial_weight=1000)
    gone = await _add_spool(client, fil["id"], initial_weight=1000)
    # Archive the second spool — it must drop out of both aggregates.
    resp = await client.patch(f"{SPOOL}/{gone['id']}", json={"archived": True})
    assert resp.status_code == 200, resp.text

    got = await _get_filament(client, fil["id"])
    assert got["spool_count"] == 1
    assert got["remaining_weight"] == pytest.approx(1000)
    assert keep["id"] != gone["id"]


async def test_aggregate_matches_sum_of_individual_spool_remaining(client: AsyncClient):
    # Robust oracle: whatever the API decides each spool's remaining_weight is, the filament
    # aggregate must equal their sum (nulls counted as zero).
    fil = await _add_filament(client, name="ABS", weight=800)
    spools = [
        await _add_spool(client, fil["id"], initial_weight=800),
        await _add_spool(client, fil["id"], initial_weight=500),
        await _add_spool(client, fil["id"]),  # no initial_weight -> API derives it from filament.weight
    ]
    await _use(client, spools[0]["id"], 100)
    await _use(client, spools[1]["id"], 100)

    expected = 0.0
    for spool in spools:
        fetched = (await client.get(f"{SPOOL}/{spool['id']}")).json()
        expected += fetched.get("remaining_weight") or 0

    got = await _get_filament(client, fil["id"])
    assert got["spool_count"] == 3
    assert got["remaining_weight"] == pytest.approx(expected)


async def test_filament_without_spools_reports_zero(client: AsyncClient):
    fil = await _add_filament(client, name="Empty", weight=1000)
    listed = {f["id"]: f for f in await _list_filaments(client)}
    assert listed[fil["id"]]["spool_count"] == 0
    assert listed[fil["id"]]["remaining_weight"] == pytest.approx(0)


async def test_low_stock_threshold_and_reserve_count_roundtrip(client: AsyncClient):
    fil = await _add_filament(client, name="Threshold", weight=1000, low_stock_threshold=500, reserve_count=2)
    assert fil["low_stock_threshold"] == pytest.approx(500)
    assert fil["reserve_count"] == 2

    # PATCH updates them.
    resp = await client.patch(f"{FIL}/{fil['id']}", json={"low_stock_threshold": 300})
    assert resp.status_code == 200, resp.text
    assert resp.json()["low_stock_threshold"] == pytest.approx(300)
    assert resp.json()["reserve_count"] == 2


async def test_new_fields_absent_when_unset(client: AsyncClient):
    # response_model_exclude_none: an unset threshold/reserve must be omitted, not null, so the
    # payload stays minimal for integrations.
    fil = await _add_filament(client, name="Bare", weight=1000)
    assert "low_stock_threshold" not in fil
    assert "reserve_count" not in fil


async def test_sort_by_spool_count(client: AsyncClient):
    one = await _add_filament(client, name="one", weight=1000)
    two = await _add_filament(client, name="two", weight=1000)
    three = await _add_filament(client, name="three", weight=1000)
    for _ in range(1):
        await _add_spool(client, one["id"], initial_weight=1000)
    for _ in range(2):
        await _add_spool(client, two["id"], initial_weight=1000)
    for _ in range(3):
        await _add_spool(client, three["id"], initial_weight=1000)

    ordered = await _list_filaments(client, sort="spool_count:desc")
    ids_in_order = [f["id"] for f in ordered]
    assert ids_in_order == [three["id"], two["id"], one["id"]]


async def test_sort_by_remaining_weight_ascending(client: AsyncClient):
    low = await _add_filament(client, name="low", weight=1000)
    mid = await _add_filament(client, name="mid", weight=1000)
    high = await _add_filament(client, name="high", weight=1000)
    # remaining: low=200, mid=600, high=1000
    s_low = await _add_spool(client, low["id"], initial_weight=1000)
    await _use(client, s_low["id"], 800)
    s_mid = await _add_spool(client, mid["id"], initial_weight=1000)
    await _use(client, s_mid["id"], 400)
    await _add_spool(client, high["id"], initial_weight=1000)

    ordered = await _list_filaments(client, sort="remaining_weight:asc")
    ids_in_order = [f["id"] for f in ordered]
    assert ids_in_order == [low["id"], mid["id"], high["id"]]


async def test_aggregates_absent_from_nested_spool_filament(client: AsyncClient):
    # The nested filament inside a spool payload must NOT carry the aggregates — it would be an N+1
    # and, more importantly, a change to the wire shape integrations depend on.
    fil = await _add_filament(client, name="Nested", weight=1000)
    await _add_spool(client, fil["id"], initial_weight=1000)

    spools = (await client.get(SPOOL)).json()
    assert len(spools) == 1
    nested = spools[0]["filament"]
    assert "spool_count" not in nested
    assert "remaining_weight" not in nested


async def test_vendor_aggregates(client: AsyncClient):
    vendor_resp = await client.post(VENDOR, json={"name": "Acme"})
    assert vendor_resp.status_code == 200, vendor_resp.text
    vendor_id = vendor_resp.json()["id"]

    fil_a = await _add_filament(client, name="A", weight=1000, vendor_id=vendor_id)
    fil_b = await _add_filament(client, name="B", weight=1000, vendor_id=vendor_id)
    await _add_spool(client, fil_a["id"], initial_weight=1000)
    await _add_spool(client, fil_a["id"], initial_weight=1000)
    archived = await _add_spool(client, fil_b["id"], initial_weight=1000)
    await client.patch(f"{SPOOL}/{archived['id']}", json={"archived": True})

    got = (await client.get(f"{VENDOR}/{vendor_id}")).json()
    assert got["filament_count"] == 2
    # Two active spools on fil_a; fil_b's only spool is archived, so it is excluded.
    assert got["spool_count"] == 2


async def test_vendor_aggregates_absent_from_nested_filament_vendor(client: AsyncClient):
    vendor_resp = await client.post(VENDOR, json={"name": "Nested Vendor"})
    vendor_id = vendor_resp.json()["id"]
    await _add_filament(client, name="withvendor", weight=1000, vendor_id=vendor_id)

    filaments = await _list_filaments(client)
    nested_vendor = next(f["vendor"] for f in filaments if f.get("vendor"))
    assert "filament_count" not in nested_vendor
    assert "spool_count" not in nested_vendor
