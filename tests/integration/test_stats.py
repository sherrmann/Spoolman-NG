"""Integration tests for the usage-stats endpoint (#81).

Drives real PUT /use, PUT /measure and PATCH /spool calls, then asserts GET /stats/usage aggregates
the resulting usage-event log into consumption + cost buckets, counts only real consumption events,
and honours the from/to range filter.
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
STATS = "/api/v1/stats/usage"


async def _make_spool(
    client: AsyncClient,
    *,
    filament_price: float | None = None,
    filament_weight: float | None = None,
    spool_price: float | None = None,
    initial_weight: float = 1000,
    spool_weight: float = 200,
) -> dict:
    fil_body: dict = {"density": 1.24, "diameter": 1.75, "name": "PLA"}
    if filament_price is not None:
        fil_body["price"] = filament_price
    if filament_weight is not None:
        fil_body["weight"] = filament_weight
    fil = await client.post(FIL, json=fil_body)
    assert fil.status_code == 200, fil.text

    sp_body: dict = {"filament_id": fil.json()["id"], "initial_weight": initial_weight, "spool_weight": spool_weight}
    if spool_price is not None:
        sp_body["price"] = spool_price
    sp = await client.post(SPOOL, json=sp_body)
    assert sp.status_code == 200, sp.text
    return sp.json()


async def _usage(client: AsyncClient, params: dict | None = None) -> list[dict]:
    resp = await client.get(STATS, params=params or {})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_empty_log_returns_no_buckets(client: AsyncClient):
    await _make_spool(client)
    assert await _usage(client) == []


async def test_use_events_sum_into_one_bucket(client: AsyncClient):
    spool = await _make_spool(client)
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 100})
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 50})

    result = await _usage(client)
    assert len(result) == 1
    assert result[0]["consumed_weight"] == 150


async def test_cost_uses_filament_price_per_gram(client: AsyncClient):
    # 25 currency for a 1000 g net spool → 0.025/g. Using 100 g costs 2.5.
    spool = await _make_spool(client, filament_price=25, filament_weight=1000, initial_weight=1000)
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 100})

    result = await _usage(client)
    assert len(result) == 1
    assert result[0]["cost"] == 2.5


async def test_spool_price_overrides_filament_price(client: AsyncClient):
    # Spool overrides the filament price with 50 → 0.05/g; using 100 g costs 5.
    spool = await _make_spool(client, filament_price=25, filament_weight=1000, spool_price=50, initial_weight=1000)
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 100})

    result = await _usage(client)
    assert result[0]["cost"] == 5.0


async def test_cost_is_zero_without_price(client: AsyncClient):
    spool = await _make_spool(client, filament_weight=1000)
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 100})

    result = await _usage(client)
    assert result[0]["consumed_weight"] == 100
    assert result[0]["cost"] == 0


async def test_measure_events_are_counted(client: AsyncClient):
    spool = await _make_spool(client, initial_weight=1000, spool_weight=200)
    # Gross 900 → net used = (1000+200) - 900 = 300.
    await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 900})

    result = await _usage(client)
    assert len(result) == 1
    assert result[0]["consumed_weight"] == 300


async def test_patch_update_events_are_excluded(client: AsyncClient):
    """A used_weight edit / reset logs an 'update' event, which is not real consumption."""
    spool = await _make_spool(client)
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 100})
    # Reset usage back to 0 → an 'update' event of delta -100.
    await client.patch(f"{SPOOL}/{spool['id']}", json={"used_weight": 0})

    result = await _usage(client)
    # Only the +100 use is counted; the -100 update is excluded (else this would net to 0).
    assert len(result) == 1
    assert result[0]["consumed_weight"] == 100


async def test_bucket_granularity_changes_the_period_label(client: AsyncClient):
    spool = await _make_spool(client)
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 10})

    by_day = await _usage(client, {"bucket": "day"})
    by_year = await _usage(client, {"bucket": "year"})
    # Same single event, labelled at different granularities: YYYY-MM-DD vs YYYY.
    assert len(by_day[0]["period"]) == len("YYYY-MM-DD")
    assert len(by_year[0]["period"]) == len("YYYY")


async def test_to_before_events_excludes_them(client: AsyncClient):
    spool = await _make_spool(client)
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 10})
    # Everything happened "now"; a cut-off in the past excludes it all.
    assert await _usage(client, {"to": "2000-01-01T00:00:00"}) == []


async def test_from_after_events_excludes_them(client: AsyncClient):
    spool = await _make_spool(client)
    await client.put(f"{SPOOL}/{spool['id']}/use", json={"use_weight": 10})
    # A start far in the future excludes everything recorded now.
    assert await _usage(client, {"from": "2100-01-01T00:00:00"}) == []
