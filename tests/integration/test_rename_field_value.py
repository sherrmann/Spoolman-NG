"""Integration tests for PATCH /spool/field/{field}.

Ported from upstream's rename_field_value (spoolman/database/spool.py and its
/spool/field/{field} endpoint). Renames one value of a spool field (the string ``location``, or
one of the spool's own text/single-choice extra fields) everywhere it occurs, including on
archived spools, merging into any spool that already holds the new value.
"""

from httpx import AsyncClient

FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
FIELD = "/api/v1/field/spool"


async def _filament(client: AsyncClient) -> dict:
    resp = await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "weight": 1000})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _spool(client: AsyncClient, filament_id: int, **fields: object) -> dict:
    resp = await client.post(SPOOL, json={"filament_id": filament_id, **fields})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_rename_location_value_updates_every_spool_including_archived(client: AsyncClient):
    fil = await _filament(client)
    bottom1 = await _spool(client, fil["id"], location="Bottom")
    bottom2 = await _spool(client, fil["id"], location="Bottom", archived=True)
    top = await _spool(client, fil["id"], location="Top")

    resp = await client.patch(f"{SPOOL}/field/location", json={"value": "Bottom", "new_value": "Lower"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"spools_updated": 2}

    for spool_id in (bottom1["id"], bottom2["id"]):
        got = await client.get(f"{SPOOL}/{spool_id}")
        assert got.json()["location"] == "Lower"

    unaffected = await client.get(f"{SPOOL}/{top['id']}")
    assert unaffected.json()["location"] == "Top"


async def test_rename_onto_existing_value_merges(client: AsyncClient):
    """Renaming "Bottom" onto "Top", which already exists, merges the two -- no duplication."""
    fil = await _filament(client)
    bottom = await _spool(client, fil["id"], location="Bottom")
    top = await _spool(client, fil["id"], location="Top")

    resp = await client.patch(f"{SPOOL}/field/location", json={"value": "Bottom", "new_value": "Top"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"spools_updated": 1}

    for spool_id in (bottom["id"], top["id"]):
        got = await client.get(f"{SPOOL}/{spool_id}")
        assert got.json()["location"] == "Top"

    # And grouping now reports one merged group of two, not two groups.
    group_resp = await client.get(
        f"{SPOOL}/group",
        params={"group_by": "location", "filament.id": str(fil["id"])},
    )
    groups = {g["key"]: g["spool_count"] for g in group_resp.json()}
    assert groups == {"Top": 2}


async def test_rename_location_over_max_length_is_400(client: AsyncClient):
    fil = await _filament(client)
    await _spool(client, fil["id"], location="Bottom")

    resp = await client.patch(
        f"{SPOOL}/field/location",
        json={"value": "Bottom", "new_value": "x" * 65},
    )
    assert resp.status_code == 400, resp.text


async def test_rename_extra_field_value_updates_every_spool_including_archived(client: AsyncClient):
    resp = await client.post(f"{FIELD}/shelf", json={"name": "Shelf", "field_type": "text"})
    assert resp.status_code == 200, resp.text

    fil = await _filament(client)
    bottom1 = await _spool(client, fil["id"], extra={"shelf": '"Bottom"'})
    bottom2 = await _spool(client, fil["id"], extra={"shelf": '"Bottom"'}, archived=True)
    top = await _spool(client, fil["id"], extra={"shelf": '"Top"'})

    resp = await client.patch(f"{SPOOL}/field/extra.shelf", json={"value": "Bottom", "new_value": "Lower"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"spools_updated": 2}

    for spool_id in (bottom1["id"], bottom2["id"]):
        got = await client.get(f"{SPOOL}/{spool_id}")
        assert got.json()["extra"]["shelf"] == '"Lower"'

    unaffected = await client.get(f"{SPOOL}/{top['id']}")
    assert unaffected.json()["extra"]["shelf"] == '"Top"'


async def test_rename_extra_field_value_onto_existing_merges(client: AsyncClient):
    resp = await client.post(f"{FIELD}/shelf", json={"name": "Shelf", "field_type": "text"})
    assert resp.status_code == 200, resp.text

    fil = await _filament(client)
    bottom = await _spool(client, fil["id"], extra={"shelf": '"Bottom"'})
    top = await _spool(client, fil["id"], extra={"shelf": '"Top"'})

    resp = await client.patch(f"{SPOOL}/field/extra.shelf", json={"value": "Bottom", "new_value": "Top"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"spools_updated": 1}

    for spool_id in (bottom["id"], top["id"]):
        got = await client.get(f"{SPOOL}/{spool_id}")
        assert got.json()["extra"]["shelf"] == '"Top"'


async def test_rename_unknown_extra_field_is_400(client: AsyncClient):
    resp = await client.patch(f"{SPOOL}/field/extra.nope", json={"value": "a", "new_value": "b"})
    assert resp.status_code == 400, resp.text


async def test_rename_filament_owned_field_is_rejected(client: AsyncClient):
    """material/vendor belong to the filament, not the spool -- rename_field_value refuses them."""
    resp = await client.patch(f"{SPOOL}/field/material", json={"value": "PLA", "new_value": "PETG"})
    assert resp.status_code == 400, resp.text


async def test_rename_multi_choice_extra_field_is_rejected(client: AsyncClient):
    resp = await client.post(
        f"{FIELD}/color",
        json={"name": "Color", "field_type": "choice", "choices": ["Red", "Blue"], "multi_choice": True},
    )
    assert resp.status_code == 200, resp.text

    resp = await client.patch(f"{SPOOL}/field/extra.color", json={"value": "Red", "new_value": "Green"})
    assert resp.status_code == 400, resp.text
