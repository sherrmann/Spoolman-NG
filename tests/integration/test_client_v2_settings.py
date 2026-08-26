"""Integration tests for the client_v2 (Svelte) settings ported from upstream's settings.py.

label_designs backs the Konva label designer on the /labels page; dashboard_groups and
dashboard_spoolorders back the group-by-anything /dashboard page's saved layout. This fork's
settings.py never registered any of the three (the React client does not use them), so GET/POST
against them 404'd with "Setting <key> does not exist." and both client_v2 pages degraded to an
empty, non-persistent state. See spoolman/settings.py and upstream's for the registrations, and
client_v2/src/lib/api/labelDesigns.ts / client_v2/src/lib/dashboard/layout.ts for how the vendored
client reads and writes them.

Wire format note: a setting's "value" is itself a JSON-encoded string, and POST /setting/{key}
takes that JSON text as a plain `str` body over `content-type: application/json` -- so FastAPI's
own JSON decode of the wire body must be undone by encoding the payload *twice* on the way in
(see tests/integration/test_setting_oversized_value.py for the full explanation). Every existing
setting test in this suite follows this convention.
"""

import json

from httpx import AsyncClient

HEADERS = {"content-type": "application/json"}

LABEL_DESIGNS = "/api/v1/setting/label_designs"
DASHBOARD_GROUPS = "/api/v1/setting/dashboard_groups"
DASHBOARD_SPOOLORDERS = "/api/v1/setting/dashboard_spoolorders"

# A realistic (if small) label design, matching the shape client_v2's LabelDesign type expects.
SAMPLE_DESIGN = {
    "id": "d1a2b3c4-5678-90ab-cdef-1234567890ab",
    "name": "Standard Spool Label",
    "kind": "spool",
    "label": {"w": 90, "h": 29},
    "elements": [
        {"id": "el-1", "type": "qr", "x": 2, "y": 2, "size": 20, "ec": "H", "encoding": "scheme", "logo": True},
        {
            "id": "el-2",
            "type": "text",
            "x": 24,
            "y": 2,
            "w": 64,
            "fontSize": 4,
            "bold": True,
            "align": "left",
            "color": "#000000",
            "wrap": True,
            "template": "**{filament.vendor.name} {filament.name}**",
        },
    ],
    "layout": {
        "mode": "sheet",
        "exportFormat": "png",
        "dpi": 300,
        "paper": "A4",
        "custom": {"w": 210, "h": 297},
        "landscape": False,
        "margin": {"t": 10, "b": 10, "l": 10, "r": 10},
        "gap": {"x": 2, "y": 2},
        "columns": 2,
        "rows": 8,
    },
}


async def test_label_designs_has_registered_default(client: AsyncClient):
    resp = await client.get(LABEL_DESIGNS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_set"] is False
    assert body["type"] == "array"
    assert json.loads(body["value"]) == []


async def test_label_designs_round_trips_through_the_api(client: AsyncClient):
    payload = [SAMPLE_DESIGN]
    resp = await client.post(LABEL_DESIGNS, content=json.dumps(json.dumps(payload)), headers=HEADERS)
    assert resp.status_code == 200, resp.text

    resp = await client.get(LABEL_DESIGNS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_set"] is True
    assert json.loads(body["value"]) == payload


async def test_label_designs_rejects_non_array(client: AsyncClient):
    resp = await client.post(LABEL_DESIGNS, content=json.dumps(json.dumps({"not": "an array"})), headers=HEADERS)
    assert resp.status_code == 400, resp.text


async def test_dashboard_groups_has_registered_default(client: AsyncClient):
    resp = await client.get(DASHBOARD_GROUPS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_set"] is False
    assert body["type"] == "object"
    assert json.loads(body["value"]) == {}


async def test_dashboard_groups_round_trips_through_the_api(client: AsyncClient):
    payload = {"location": ["Shelf A", "Shelf B", ""], "material": ["PLA", "PETG"]}
    resp = await client.post(DASHBOARD_GROUPS, content=json.dumps(json.dumps(payload)), headers=HEADERS)
    assert resp.status_code == 200, resp.text

    resp = await client.get(DASHBOARD_GROUPS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_set"] is True
    assert json.loads(body["value"]) == payload


async def test_dashboard_groups_rejects_non_object(client: AsyncClient):
    resp = await client.post(DASHBOARD_GROUPS, content=json.dumps(json.dumps(["not", "an", "object"])), headers=HEADERS)
    assert resp.status_code == 400, resp.text


async def test_dashboard_spoolorders_round_trips_through_the_api(client: AsyncClient):
    payload = {"location": {"Shelf A": [3, 1, 2], "": [7]}}
    resp = await client.post(DASHBOARD_SPOOLORDERS, content=json.dumps(json.dumps(payload)), headers=HEADERS)
    assert resp.status_code == 200, resp.text

    resp = await client.get(DASHBOARD_SPOOLORDERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_set"] is True
    assert json.loads(body["value"]) == payload


async def test_dashboard_spoolorders_rejects_non_object(client: AsyncClient):
    resp = await client.post(
        DASHBOARD_SPOOLORDERS,
        content=json.dumps(json.dumps([1, 2, 3])),
        headers=HEADERS,
    )
    assert resp.status_code == 400, resp.text
