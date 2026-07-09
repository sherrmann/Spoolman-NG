"""Integration tests for the per-spool diameter override (B13a: #101).

A spool may carry its own measured diameter that overrides the filament's nominal diameter in
length math, while still round-tripping the raw override value. With no override the behaviour is
byte-identical to before, so integrations reporting by length are unaffected unless a spool opts in.
"""

import pytest
from httpx import AsyncClient

from spoolman.math import weight_from_length

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"

DENSITY = 1.24
FIL_DIAMETER = 1.75
SPOOL_DIAMETER = 2.5


async def _filament(client: AsyncClient) -> dict:
    resp = await client.post(FIL, json={"density": DENSITY, "diameter": FIL_DIAMETER, "name": "PLA", "weight": 1000})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_override_round_trips_and_is_null_by_default(client: AsyncClient):
    fil = await _filament(client)
    plain = (await client.post(SPOOL, json={"filament_id": fil["id"]})).json()
    overridden = (await client.post(SPOOL, json={"filament_id": fil["id"], "diameter": SPOOL_DIAMETER})).json()

    # No override ⇒ the field is omitted (response_model_exclude_none); an override round-trips raw.
    assert "diameter" not in plain
    assert overridden["diameter"] == SPOOL_DIAMETER
    assert (await client.get(f"{SPOOL}/{overridden['id']}")).json()["diameter"] == SPOOL_DIAMETER


async def test_use_length_uses_the_override_diameter(client: AsyncClient):
    fil = await _filament(client)
    plain = (await client.post(SPOOL, json={"filament_id": fil["id"]})).json()
    overridden = (await client.post(SPOOL, json={"filament_id": fil["id"], "diameter": SPOOL_DIAMETER})).json()

    length = 1000.0
    for spool_id in (plain["id"], overridden["id"]):
        resp = await client.put(f"{SPOOL}/{spool_id}/use", json={"use_length": length})
        assert resp.status_code == 200, resp.text

    plain_after = (await client.get(f"{SPOOL}/{plain['id']}")).json()
    over_after = (await client.get(f"{SPOOL}/{overridden['id']}")).json()

    # The consumed weight is computed with the effective diameter: the plain spool uses the filament's
    # 1.75 mm, the overridden spool its own 2.5 mm — the thicker filament weighs more per mm.
    assert plain_after["used_weight"] == pytest.approx(
        weight_from_length(length=length, diameter=FIL_DIAMETER, density=DENSITY)
    )
    assert over_after["used_weight"] == pytest.approx(
        weight_from_length(length=length, diameter=SPOOL_DIAMETER, density=DENSITY)
    )
    assert over_after["used_weight"] > plain_after["used_weight"]

    # used_length inverts back through the same effective diameter, so both round-trip to ~1000 mm.
    assert plain_after["used_length"] == pytest.approx(length, rel=1e-6)
    assert over_after["used_length"] == pytest.approx(length, rel=1e-6)


async def test_sort_by_remaining_length_respects_override(client: AsyncClient):
    """Two spools with equal remaining weight sort differently once one has a thinner override."""
    fil = await _filament(client)
    # Equal initial weight; the thin-diameter override yields MORE remaining length for the same weight.
    thick = (await client.post(SPOOL, json={"filament_id": fil["id"], "diameter": 3.0})).json()
    thin = (await client.post(SPOOL, json={"filament_id": fil["id"], "diameter": 1.0})).json()

    resp = await client.get(SPOOL, params={"sort": "remaining_length:desc"})
    assert resp.status_code == 200, resp.text
    ordered = [row["id"] for row in resp.json()]
    # Thinner filament ⇒ greater length for the same remaining weight ⇒ sorts first descending.
    assert ordered.index(thin["id"]) < ordered.index(thick["id"])
