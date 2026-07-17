"""Integration tests for PUT /spool/{id}/measure when no empty-spool (tare) weight is configured.

A filament without spool_weight is common — many users never weigh an empty spool. measure()
falls back from the spool's spool_weight to the filament's, but nothing guarded the case where
both are unset: initial_gross_weight = initial_weight + None raised a TypeError that surfaced
as an unhandled 500 (#229). An unknown tare must be treated as 0, matching how the
remaining-weight math tolerates a missing tare everywhere else.
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"


async def _add_filament(client: AsyncClient, **fields: object) -> dict:
    body = {"density": 1.24, "diameter": 1.75, **fields}
    resp = await client.post(FIL, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _add_spool(client: AsyncClient, filament_id: int, **fields: object) -> dict:
    resp = await client.post(SPOOL, json={"filament_id": filament_id, **fields})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_measure_without_any_tare_weight_treats_tare_as_zero(client: AsyncClient):
    filament = await _add_filament(client, weight=1000)  # no spool_weight anywhere
    spool = await _add_spool(client, filament["id"])  # initial_weight defaults to filament weight

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 800})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used_weight"] == 200
    assert body["remaining_weight"] == 800


async def test_measure_above_gross_without_tare_resets_initial_weight(client: AsyncClient):
    filament = await _add_filament(client, weight=1000)
    spool = await _add_spool(client, filament["id"])

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 1200})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["initial_weight"] == 1200
    assert body["used_weight"] == 0


async def test_measure_with_filament_tare_still_subtracts_it(client: AsyncClient):
    filament = await _add_filament(client, weight=1000, spool_weight=200)
    spool = await _add_spool(client, filament["id"])

    resp = await client.put(f"{SPOOL}/{spool['id']}/measure", json={"weight": 700})

    assert resp.status_code == 200, resp.text
    assert resp.json()["used_weight"] == 500
