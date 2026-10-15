"""SQLite search, filters and sorting fold case for non-ASCII letters too (upstream 1507f9b3b).

SQLite's built-in lower() only folds A-Z, so "червоний" did not find "Червоний" and "ölfass"
sorted apart from "Ölmann". Each connection now gets a Unicode lower(); ilike() and the
case-insensitive sorts both go through it.
"""

from typing import Any

from httpx import AsyncClient

FIL = "/api/v1/filament"
VENDOR = "/api/v1/vendor"


async def _filament(client: AsyncClient, name: str) -> dict[str, Any]:
    resp = await client.post(FIL, json={"name": name, "density": 1.25, "diameter": 1.75})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_search_finds_a_cyrillic_name_typed_in_lower_case(client: AsyncClient):
    filament = await _filament(client, "Червоний")

    resp = await client.get("/api/v1/search", params={"q": "червоний"})

    assert resp.status_code == 200, resp.text
    assert filament["id"] in [hit["filament"]["id"] for hit in resp.json()["filaments"]]


async def test_name_filter_matches_an_accented_capital(client: AsyncClient):
    filament = await _filament(client, "Ärger Grün")
    await _filament(client, "Something else")

    resp = await client.get(FIL, params={"name": "ärger"})

    assert resp.status_code == 200, resp.text
    assert [f["id"] for f in resp.json()] == [filament["id"]]


async def test_sort_folds_case_for_non_ascii_initials(client: AsyncClient):
    for name in ("Ölmann", "Zebra", "ölfass"):
        assert (await client.post(VENDOR, json={"name": name})).status_code == 200

    resp = await client.get(VENDOR, params={"sort": "name:asc"})

    assert resp.status_code == 200, resp.text
    # Ö and ö sort after z by code point either way; what changes is that the two now fold to
    # one letter, so "ölfass" comes before "Ölmann". ASCII-only lower() kept them apart.
    assert [v["name"] for v in resp.json()] == ["Zebra", "ölfass", "Ölmann"]
