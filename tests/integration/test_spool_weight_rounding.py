"""Integration tests for the Python-side used_weight rounding in spoolman/database/spool.py (#377).

used_weight is rounded to WEIGHT_ROUND_DECIMALS (6) places on every write path to strip float64
representation noise (e.g. 0.1 + 0.2 == 0.30000000000000004) without discarding real sub-gram
increments. The SQL-side rounding (_round6, used by use_weight_safe) is covered by
tests_integration/tests/spool/test_use.py, but that suite needs a live server plus Docker and does
not run in the fast job. The three Python-side `round(..., WEIGHT_ROUND_DECIMALS)` calls had no
coverage at all in the fast suite:

  1. build() -- rounds used_weight at spool creation, whichever branch derived it.
  2. update()'s remaining_weight branch -- derives used_weight from a supplied remaining_weight,
     then rounds it.
  3. update()'s used_weight branch -- rounds a directly-supplied used_weight.

Each test below picks inputs that land on genuine float64 noise (not just any fraction), so the
assertion can only pass if the rounding actually happened -- an unrounded value would fail these
by more than float epsilon, not by a hair.
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"


async def _add_filament(client: AsyncClient, **fields: object) -> dict:
    body = {"density": 1.24, "diameter": 1.75, "name": "PLA", **fields}
    resp = await client.post(FIL, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_build_rounds_used_weight_noise_on_creation(client: AsyncClient):
    """build() must round a directly-supplied used_weight that carries float64 noise.

    0.1 + 0.2 in float64 is 0.30000000000000004, not 0.3 -- classic representation noise. Supplying
    that literal as used_weight at creation exercises build()'s `used_weight = round(used_weight,
    WEIGHT_ROUND_DECIMALS)` line directly (the earlier branches that compute used_weight from
    remaining_weight are not involved here, since used_weight is supplied outright).
    """
    filament = await _add_filament(client)
    noisy_used_weight = 0.1 + 0.2
    assert noisy_used_weight == 0.30000000000000004  # sanity: this literal really is noisy

    resp = await client.post(SPOOL, json={"filament_id": filament["id"], "used_weight": noisy_used_weight})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["used_weight"] == 0.3


async def test_update_used_weight_branch_rounds_noise(client: AsyncClient):
    """update()'s `used_weight` branch must round a directly-supplied noisy value."""
    filament = await _add_filament(client)
    resp = await client.post(SPOOL, json={"filament_id": filament["id"]})
    assert resp.status_code == 200, resp.text
    spool_id = resp.json()["id"]

    noisy_used_weight = 0.1 + 0.2
    resp = await client.patch(f"{SPOOL}/{spool_id}", json={"used_weight": noisy_used_weight})
    assert resp.status_code == 200, resp.text
    assert resp.json()["used_weight"] == 0.3


async def test_update_remaining_weight_branch_rounds_derived_used_weight(client: AsyncClient):
    """update()'s `remaining_weight` branch derives used_weight, then must round the result.

    initial_weight=1000, remaining_weight=999.7 subtracts to 0.2999999999999545 in float64 -- noise
    on the order of 1e-13, well above machine epsilon for this magnitude, and nowhere near 0.3
    without the round() call. This exercises the derivation-then-round path distinctly from the
    directly-supplied used_weight branch above.
    """
    filament = await _add_filament(client)
    resp = await client.post(SPOOL, json={"filament_id": filament["id"], "initial_weight": 1000})
    assert resp.status_code == 200, resp.text
    spool_id = resp.json()["id"]

    derived_noise = 1000 - 999.7
    assert derived_noise == 0.2999999999999545  # sanity: the raw subtraction really is noisy

    resp = await client.patch(f"{SPOOL}/{spool_id}", json={"remaining_weight": 999.7})
    assert resp.status_code == 200, resp.text
    assert resp.json()["used_weight"] == 0.3
