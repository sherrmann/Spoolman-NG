"""Integration tests for the slicer-profile export endpoint (#76).

Creates a real filament (with a vendor, temps, colour and price) and asserts GET
/export/filament/{id}/slicer returns a correctly-mapped profile for each slicer, with a download
Content-Disposition and the right media type.
"""

import json
from xml.etree import ElementTree as ET

import pytest
from httpx import AsyncClient

from spoolman.exceptions import ItemNotFoundError

FIL = "/api/v1/filament"
VENDOR = "/api/v1/vendor"
EXPORT = "/api/v1/export/filament"


async def _make_filament(client: AsyncClient) -> dict:
    vnd = await client.post(VENDOR, json={"name": "Prusament"})
    assert vnd.status_code == 200, vnd.text
    fil = await client.post(
        FIL,
        json={
            "name": "Galaxy Black",
            "vendor_id": vnd.json()["id"],
            "material": "PETG",
            "density": 1.27,
            "diameter": 1.75,
            "weight": 1000,
            "price": 25,
            "settings_extruder_temp": 240,
            "settings_bed_temp": 80,
            "color_hex": "1A2B3C",
        },
    )
    assert fil.status_code == 200, fil.text
    return fil.json()


async def test_prusa_profile_download(client: AsyncClient):
    fil = await _make_filament(client)
    resp = await client.get(f"{EXPORT}/{fil['id']}/slicer", params={"slicer": "prusa"})
    assert resp.status_code == 200, resp.text
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["content-disposition"].endswith('.ini"')
    body = resp.text
    assert "filament_type = PETG" in body
    assert "temperature = 240" in body
    assert "bed_temperature = 80" in body
    assert "filament_colour = #1A2B3C" in body
    assert "filament_cost = 25.0" in body


async def test_orca_profile_download(client: AsyncClient):
    fil = await _make_filament(client)
    resp = await client.get(f"{EXPORT}/{fil['id']}/slicer", params={"slicer": "orca"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    data = json.loads(resp.text)
    assert data["filament_type"] == ["PETG"]
    assert data["nozzle_temperature"] == ["240"]
    assert data["name"] == "Prusament Galaxy Black"


async def test_cura_profile_download(client: AsyncClient):
    fil = await _make_filament(client)
    resp = await client.get(f"{EXPORT}/{fil['id']}/slicer", params={"slicer": "cura"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-disposition"].endswith('.xml.fdm_material"')
    ns = {"m": "http://www.ultimaker.com/material"}
    root = ET.fromstring(resp.text)  # noqa: S314 - trusted, server-generated XML
    assert root.find("m:properties/m:diameter", ns).text == "1.75"
    assert root.find("m:metadata/m:name/m:material", ns).text == "PETG"


async def test_unknown_filament_is_not_found(client: AsyncClient):
    # The router-only harness doesn't install the ItemNotFoundError->404 handler, so it raises here;
    # against the full app this surfaces as a 404.
    with pytest.raises(ItemNotFoundError):
        await client.get(f"{EXPORT}/999999/slicer", params={"slicer": "prusa"})
