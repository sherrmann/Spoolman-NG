"""Integration tests for GET /field/{entity_type}/{key}/values.

Ported from upstream's field.py (find_extra_field_values, spoolman/database/extra_field_query.py).
Lists the distinct values currently stored for one extra field, mirroring the built-in
distinct-value endpoints such as /material and /location -- intended for populating filter
option lists for text and choice fields.
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
FIELD = "/api/v1/field/spool"


async def _filament(client: AsyncClient) -> dict:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "weight": 1000})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_values_lists_distinct_sorted_non_empty_values(client: AsyncClient):
    resp = await client.post(f"{FIELD}/shelf", json={"name": "Shelf", "field_type": "text"})
    assert resp.status_code == 200, resp.text

    fil = await _filament(client)
    for value in ('"Top"', '"Bottom"', '"Top"', '""', None):
        payload = {"filament_id": fil["id"]}
        if value is not None:
            payload["extra"] = {"shelf": value}
        resp = await client.post(SPOOL, json=payload)
        assert resp.status_code == 200, resp.text

    resp = await client.get(f"{FIELD}/shelf/values")
    assert resp.status_code == 200, resp.text
    # Distinct, sorted, and neither the empty string nor the un-set spool contribute a value.
    assert resp.json() == ["Bottom", "Top"]


async def test_values_for_unknown_key_is_404(client: AsyncClient):
    resp = await client.get(f"{FIELD}/nope/values")
    assert resp.status_code == 404, resp.text


async def test_values_for_field_with_no_spools_is_empty(client: AsyncClient):
    resp = await client.post(f"{FIELD}/owner", json={"name": "Owner", "field_type": "text"})
    assert resp.status_code == 200, resp.text

    resp = await client.get(f"{FIELD}/owner/values")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
