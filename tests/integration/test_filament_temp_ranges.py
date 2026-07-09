"""Integration tests for filament extruder/bed temperature ranges (issue #112).

Filaments used to store only single recommended extruder/bed temperatures; a manufacturer's
recommended min/max range had nowhere to go. These drive the real POST/GET/PATCH endpoints and
assert the four new optional range fields round-trip, that they stay absent (never zero-defaulted)
when unset so existing integrations see an unchanged payload, and that they can be updated and
cleared.
"""

from httpx import AsyncClient

API = "/api/v1/filament"


async def _add_filament(client: AsyncClient, **fields: object) -> dict:
    body = {"density": 1.24, "diameter": 1.75, **fields}
    resp = await client.post(API, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_temperature_ranges_round_trip_on_create_and_get(client: AsyncClient):
    filament = await _add_filament(
        client,
        settings_extruder_temp=215,
        settings_extruder_temp_min=205,
        settings_extruder_temp_max=225,
        settings_bed_temp_min=50,
        settings_bed_temp_max=60,
    )
    assert filament["settings_extruder_temp_min"] == 205
    assert filament["settings_extruder_temp_max"] == 225
    assert filament["settings_bed_temp_min"] == 50
    assert filament["settings_bed_temp_max"] == 60
    # The single recommended value is independent and still stored.
    assert filament["settings_extruder_temp"] == 215

    got = await client.get(f"{API}/{filament['id']}")
    assert got.status_code == 200, got.text
    assert got.json()["settings_extruder_temp_min"] == 205
    assert got.json()["settings_bed_temp_max"] == 60


async def test_range_fields_absent_when_unset(client: AsyncClient):
    # Purely additive: a filament created without ranges must not gain zeroed range fields, so
    # existing consumers (Moonraker/OctoPrint/HA) see a byte-identical payload.
    filament = await _add_filament(client, settings_extruder_temp=210)
    assert "settings_extruder_temp_min" not in filament
    assert "settings_extruder_temp_max" not in filament
    assert "settings_bed_temp_min" not in filament
    assert "settings_bed_temp_max" not in filament


async def test_range_can_be_patched_and_cleared(client: AsyncClient):
    filament = await _add_filament(client)
    fid = filament["id"]

    patched = await client.patch(
        f"{API}/{fid}",
        json={"settings_extruder_temp_min": 200, "settings_extruder_temp_max": 220},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["settings_extruder_temp_min"] == 200
    assert patched.json()["settings_extruder_temp_max"] == 220

    cleared = await client.patch(f"{API}/{fid}", json={"settings_extruder_temp_min": None})
    assert cleared.status_code == 200, cleared.text
    assert "settings_extruder_temp_min" not in cleared.json()
    # The other end of the range is untouched by the partial update.
    assert cleared.json()["settings_extruder_temp_max"] == 220
