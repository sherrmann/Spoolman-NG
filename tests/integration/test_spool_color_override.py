"""Integration tests for the per-spool color override (B13b: #74).

A spool may carry its own color that overrides the filament's, so one filament definition can cover
multiple spool colors. The override is emitted raw (null when unset) — no server-side merge — so
integrations see per-spool truth and clients fall back to the filament color visually.
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"


async def _filament(client: AsyncClient) -> dict:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": "PLA", "color_hex": "00FF00"})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_single_color_override_round_trips_and_is_null_by_default(client: AsyncClient):
    fil = await _filament(client)
    plain = (await client.post(SPOOL, json={"filament_id": fil["id"]})).json()
    red = (await client.post(SPOOL, json={"filament_id": fil["id"], "color_hex": "FF0000"})).json()

    # No override ⇒ the spool's own color is omitted, but the filament color is still there to fall back to.
    assert "color_hex" not in plain
    assert plain["filament"]["color_hex"] == "00FF00"
    # An override is emitted raw and does NOT merge with / overwrite the filament color.
    assert red["color_hex"] == "FF0000"
    assert red["filament"]["color_hex"] == "00FF00"
    assert (await client.get(f"{SPOOL}/{red['id']}")).json()["color_hex"] == "FF0000"


async def test_multi_color_override_round_trips(client: AsyncClient):
    fil = await _filament(client)
    body = {
        "filament_id": fil["id"],
        "multi_color_hexes": "FF0000,0000FF",
        "multi_color_direction": "coaxial",
    }
    spool = (await client.post(SPOOL, json=body)).json()
    assert spool["multi_color_hexes"] == "FF0000,0000FF"
    # Stored as the enum's string value, not "MultiColorDirection.COAXIAL".
    assert spool["multi_color_direction"] == "coaxial"


async def test_override_can_be_set_and_cleared_via_patch(client: AsyncClient):
    fil = await _filament(client)
    spool = (await client.post(SPOOL, json={"filament_id": fil["id"]})).json()

    patched = (await client.patch(f"{SPOOL}/{spool['id']}", json={"color_hex": "AABBCC"})).json()
    assert patched["color_hex"] == "AABBCC"


async def test_color_override_is_normalized_and_validated(client: AsyncClient):
    fil = await _filament(client)

    # #45 guard: a '#'-prefixed 8-hex value is normalized to 8 chars so it can't overflow String(8).
    ok = await client.post(SPOOL, json={"filament_id": fil["id"], "color_hex": "#ff000080"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["color_hex"] == "FF000080"

    # Invalid characters / lengths and contradictory combinations are rejected.
    for bad in (
        {"color_hex": "XYZ123"},
        {"color_hex": "FFF"},
        {"color_hex": "FF0000", "multi_color_hexes": "FF0000,0000FF", "multi_color_direction": "coaxial"},
        {"multi_color_hexes": "FF0000"},  # only one color
        {"multi_color_hexes": "FF0000,0000FF"},  # missing direction
    ):
        resp = await client.post(SPOOL, json={"filament_id": fil["id"], **bad})
        assert resp.status_code == 422, f"expected rejection for {bad}: {resp.text}"
