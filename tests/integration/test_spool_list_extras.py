"""The spool list and export carry every level's extra fields, once per spool (#300).

The three extra-field collections are loaded with one IN query each rather than joined into the
list query. Joined, each spool came back once per spool extra x filament extra x vendor extra;
these tests pin that the result is still exactly one row per spool with all of its values.
"""

import json

from httpx import AsyncClient

FIELD = "/api/v1/field"


async def _field(client: AsyncClient, entity: str, key: str) -> None:
    response = await client.post(f"{FIELD}/{entity}/{key}", json={"name": key, "field_type": "text"})
    assert response.status_code == 200, response.text


async def _seed(client: AsyncClient) -> list[int]:
    for entity in ("vendor", "filament", "spool"):
        for n in (1, 2):
            await _field(client, entity, f"{entity}_x{n}")
    vendor = await client.post(
        "/api/v1/vendor",
        json={"name": "Extras Co", "extra": {"vendor_x1": '"v1"', "vendor_x2": '"v2"'}},
    )
    filament = await client.post(
        "/api/v1/filament",
        json={
            "name": "Extras PLA",
            "vendor_id": vendor.json()["id"],
            "density": 1.24,
            "diameter": 1.75,
            "extra": {"filament_x1": '"f1"', "filament_x2": '"f2"'},
        },
    )
    ids = []
    for n in range(3):
        spool = await client.post(
            "/api/v1/spool",
            json={
                "filament_id": filament.json()["id"],
                "extra": {"spool_x1": json.dumps(f"s{n}"), "spool_x2": json.dumps(f"t{n}")},
            },
        )
        assert spool.status_code == 200, spool.text
        ids.append(spool.json()["id"])
    return ids


async def test_spool_list_returns_each_spool_once_with_all_extras(client: AsyncClient) -> None:
    ids = await _seed(client)

    response = await client.get("/api/v1/spool", params={"limit": 2, "sort": "id:asc"})
    page = response.json()

    assert response.headers["x-total-count"] == "3"
    assert [s["id"] for s in page] == ids[:2]
    for n, spool in enumerate(page):
        assert spool["extra"] == {"spool_x1": f'"s{n}"', "spool_x2": f'"t{n}"'}
        assert spool["filament"]["extra"] == {"filament_x1": '"f1"', "filament_x2": '"f2"'}
        assert spool["filament"]["vendor"]["extra"] == {"vendor_x1": '"v1"', "vendor_x2": '"v2"'}


async def test_export_has_one_row_per_spool_with_every_levels_extras(client: AsyncClient) -> None:
    ids = await _seed(client)

    rows = (await client.get("/api/v1/export/spools", params={"fmt": "json"})).json()

    assert sorted(r["id"] for r in rows) == ids
    row = next(r for r in rows if r["id"] == ids[1])
    assert row["extra.spool_x1"] == '"s1"'
    assert row["filament.extra.filament_x2"] == '"f2"'
    assert row["filament.vendor.extra.vendor_x1"] == '"v1"'
