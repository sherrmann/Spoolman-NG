"""Integration tests for the Location entity (B12b: #103).

Drives the new /api/v1/locations CRUD, its spool_count aggregate, and its custom-field surface
through the real endpoints, and guards the compat contract: the pre-existing string-based
GET /location (distinct spool locations) and the new entity endpoints are independent — an entity
row does not appear in the string list, and vice versa.
"""

from httpx import AsyncClient

LOC = "/api/v1/locations"
FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
FIELD = "/api/v1/field/location"


async def _add_filament(client: AsyncClient) -> dict:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": "PLA"})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _add_spool(client: AsyncClient, filament_id: int, **fields: object) -> dict:
    resp = await client.post(SPOOL, json={"filament_id": filament_id, **fields})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_location_crud_round_trip(client: AsyncClient):
    # Create
    created = (await client.post(LOC, json={"name": "Dry Box 1", "comment": "top shelf"})).json()
    assert created["name"] == "Dry Box 1"
    assert created["comment"] == "top shelf"
    assert created["extra"] == {}
    loc_id = created["id"]

    # Get
    got = await client.get(f"{LOC}/{loc_id}")
    assert got.status_code == 200
    assert got.json()["name"] == "Dry Box 1"

    # List (with x-total-count)
    listed = await client.get(LOC)
    assert listed.status_code == 200
    assert listed.headers["x-total-count"] == "1"
    assert [item["name"] for item in listed.json()] == ["Dry Box 1"]

    # Update
    patched = await client.patch(f"{LOC}/{loc_id}", json={"name": "Dry Box A"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Dry Box A"

    # Delete — the registry no longer lists it. (The not-found GET → 404 mapping is a v1-sub-app
    # exception handler that this router-only harness doesn't install, so assert via the list.)
    deleted = await client.delete(f"{LOC}/{loc_id}")
    assert deleted.status_code == 200
    empty = await client.get(LOC)
    assert empty.headers["x-total-count"] == "0"
    assert empty.json() == []


async def test_spool_count_aggregate_matches_by_name(client: AsyncClient):
    fil = await _add_filament(client)
    # Two active spools plus one archived spool at the same location name.
    await _add_spool(client, fil["id"], location="Dry Box 1")
    await _add_spool(client, fil["id"], location="Dry Box 1")
    archived = await _add_spool(client, fil["id"], location="Dry Box 1")
    await client.patch(f"{SPOOL}/{archived['id']}", json={"archived": True})

    loc = (await client.post(LOC, json={"name": "Dry Box 1"})).json()

    # Detail + list expose spool_count (non-archived only, matched by name).
    assert (await client.get(f"{LOC}/{loc['id']}")).json()["spool_count"] == 2
    assert (await client.get(LOC)).json()[0]["spool_count"] == 2

    # A registry entry with no spools reports 0, and POST itself omits the read-time aggregate.
    empty = (await client.post(LOC, json={"name": "Empty Shelf"})).json()
    assert "spool_count" not in empty  # response_model_exclude_none drops the null aggregate
    assert (await client.get(f"{LOC}/{empty['id']}")).json()["spool_count"] == 0


async def test_location_custom_fields(client: AsyncClient):
    # Define a text field on locations via the generic /field/location surface.
    resp = await client.post(f"{FIELD}/humidity", json={"name": "Humidity", "field_type": "text"})
    assert resp.status_code == 200, resp.text
    assert any(f["key"] == "humidity" for f in resp.json())

    # A location can now carry that field...
    created = (await client.post(LOC, json={"name": "Dry Box 1", "extra": {"humidity": '"32%"'}})).json()
    assert created["extra"]["humidity"] == '"32%"'
    assert (await client.get(f"{LOC}/{created['id']}")).json()["extra"]["humidity"] == '"32%"'

    # ...but an undefined field is rejected (400), same as the other entities.
    bad = await client.post(LOC, json={"name": "Bad", "extra": {"unknown": '"x"'}})
    assert bad.status_code == 400, bad.text


async def test_entity_and_string_location_endpoints_are_independent(client: AsyncClient):
    """The byte-identical GET /location (spool strings) must not be affected by the entity registry."""
    fil = await _add_filament(client)
    await _add_spool(client, fil["id"], location="Shelf X")

    # The legacy string endpoint reports the spool's location string.
    string_locs = (await client.get("/api/v1/location")).json()
    assert string_locs == ["Shelf X"]

    # Creating an entity row for a DIFFERENT name does not leak into the string list...
    await client.post(LOC, json={"name": "Dry Box 1"})
    assert (await client.get("/api/v1/location")).json() == ["Shelf X"]

    # ...and the entity list holds only the entity row (not the spool's "Shelf X" string).
    assert [item["name"] for item in (await client.get(LOC)).json()] == ["Dry Box 1"]
