"""Cross-checks between the tag subsystem and cross-entity search.

Both were ported from upstream independently, and each exercises a relationship on
``Spool`` that the other does not: search eager-loads ``filament``/``printer`` for its
own query, while ``tags`` is a second collection loaded by a different strategy. A spool
that is both tagged and returned by a search touches all of them at once, which is the
combination neither port covered on its own.
"""

import pytest
from httpx import AsyncClient

TAG_UID = "04A2B3C4D5E6F7"


async def _seed(client: AsyncClient) -> dict[str, int]:
    vendor = (await client.post("/api/v1/vendor", json={"name": "Acme"})).json()
    filament = (
        await client.post(
            "/api/v1/filament",
            json={
                "name": "PLA Red",
                "material": "PLA",
                "vendor_id": vendor["id"],
                "color_hex": "ff0000",
                "density": 1.24,
                "diameter": 1.75,
            },
        )
    ).json()
    spool = (
        await client.post(
            "/api/v1/spool",
            json={"filament_id": filament["id"], "initial_weight": 1000, "comment": "benchy"},
        )
    ).json()
    return {"vendor": vendor["id"], "filament": filament["id"], "spool": spool["id"]}


@pytest.mark.asyncio
async def test_search_returns_a_tagged_spool_without_lazy_loading(client: AsyncClient) -> None:
    """A tagged spool must serialize through search, not raise MissingGreenlet."""
    ids = await _seed(client)

    linked = await client.post(f"/api/v1/spool/{ids['spool']}/tag", json={"uid": TAG_UID, "format": "ntag"})
    assert linked.status_code == 201, linked.text

    # Match on the spool's own comment: "PLA" would match the filament instead, and a
    # filament hit carries its spools in a different shape.
    result = await client.get("/api/v1/search", params={"q": "benchy"})
    assert result.status_code == 200, result.text
    body = result.json()

    hits = [hit["spool"]["id"] for hit in body["spools"]]
    assert ids["spool"] in hits

    # The tag the spool carries must come back with it, loaded eagerly.
    tagged = next(hit["spool"] for hit in body["spools"] if hit["spool"]["id"] == ids["spool"])
    assert [entry["uid"] for entry in tagged["tags"]] == [TAG_UID]


@pytest.mark.asyncio
async def test_spool_search_by_tag_finds_the_linked_spool(client: AsyncClient) -> None:
    """The tag= filter on the spool list resolves a UID to its spool."""
    ids = await _seed(client)
    await client.post(f"/api/v1/spool/{ids['spool']}/tag", json={"uid": TAG_UID, "format": "ntag"})

    found = await client.get("/api/v1/spool", params={"tag": TAG_UID})
    assert found.status_code == 200, found.text
    assert [spool["id"] for spool in found.json()] == [ids["spool"]]


@pytest.mark.asyncio
async def test_colour_search_still_matches_when_the_spool_is_tagged(client: AsyncClient) -> None:
    """Colour search runs a different query path; a tagged spool must not disturb it."""
    ids = await _seed(client)
    await client.post(f"/api/v1/spool/{ids['spool']}/tag", json={"uid": TAG_UID, "format": "ntag"})

    result = await client.get("/api/v1/search", params={"q": "#FF0000", "color_similarity_threshold": 5})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["is_color_query"] is True
    assert ids["filament"] in [hit["filament"]["id"] for hit in body["filaments"]]
