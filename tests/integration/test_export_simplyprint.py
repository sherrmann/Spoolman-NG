"""Integration tests for the SimplyPrint export endpoint (#312)."""

from httpx import AsyncClient

EXPORT = "/api/v1/export/simplyprint"

GOLDEN_KEYS = [
    "spoolman_spool_id",
    "brand",
    "material",
    "filament_name",
    "color_hex",
    "width",
    "total_weight_grams",
    "remaining_weight_grams",
    "location_name",
    "cost",
    "lot_nr",
    "custom_note",
    "bought_at",
]


async def _filament(client: AsyncClient) -> dict:
    vnd = await client.post("/api/v1/vendor", json={"name": "Prusament"})
    fil = await client.post(
        "/api/v1/filament",
        json={
            "name": "Galaxy Black",
            "vendor_id": vnd.json()["id"],
            "material": "PETG",
            "density": 1.27,
            "diameter": 1.75,
            "weight": 1000,
            "color_hex": "1A2B3C",
        },
    )
    assert fil.status_code == 200, fil.text
    return fil.json()


async def test_simplyprint_export_excludes_archived_and_sets_headers(client: AsyncClient):
    fil = await _filament(client)
    kept = (
        await client.post(
            "/api/v1/spool",
            json={"filament_id": fil["id"], "used_weight": 100, "location": "Shelf A", "price": 20},
        )
    ).json()
    gone = (await client.post("/api/v1/spool", json={"filament_id": fil["id"]})).json()
    resp = await client.patch(f"/api/v1/spool/{gone['id']}", json={"archived": True})
    assert resp.status_code == 200, resp.text

    resp = await client.get(EXPORT)

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["content-disposition"] == 'attachment; filename="spoolman-export.json"'
    rows = resp.json()
    assert [r["spoolman_spool_id"] for r in rows] == [kept["id"]]
    assert list(rows[0]) == GOLDEN_KEYS
    assert rows[0]["brand"] == "Prusament"
    assert rows[0]["remaining_weight_grams"] == 900
    assert rows[0]["location_name"] == "Shelf A"
    assert rows[0]["cost"] == 20


async def test_simplyprint_export_empty(client: AsyncClient):
    resp = await client.get(EXPORT)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_simplyprint_route_is_not_shadowed(client: AsyncClient):
    """Other export routes must not swallow /export/simplyprint (it needs no `fmt`)."""
    resp = await client.get(EXPORT)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
