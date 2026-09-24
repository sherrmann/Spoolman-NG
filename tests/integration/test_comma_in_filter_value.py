"""A quoted filter value may contain a comma (upstream issue 1169).

The Svelte dashboard loads each card's spools with an exact, quoted filter on the card's
value, e.g. `location="Top shelf, Rack 3"`. The backend split every filter on every comma,
so that became two unmatched fuzzy parts and the card, whose header still counted the
spools, showed none of them. The same applied to extra-field filters and library chips.
"""

from httpx import AsyncClient

SPOOL = "/api/v1/spool"
FIL = "/api/v1/filament"
GROUP = "/api/v1/spool/group"
LOC = "Top shelf, Rack 3"


async def _spools(client: AsyncClient) -> dict[str, int]:
    fil = (await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "name": "Galaxy Black"})).json()
    ids = {}
    for loc in (LOC, "Top shelf", "Rack 3", "Bin 2"):
        resp = await client.post(SPOOL, json={"filament_id": fil["id"], "location": loc})
        assert resp.status_code == 200, resp.text
        ids[loc] = resp.json()["id"]
    return ids


async def test_quoted_location_with_a_comma_matches_exactly(client: AsyncClient):
    ids = await _spools(client)

    resp = await client.get(SPOOL, params={"location": f'"{LOC}"'})

    assert resp.status_code == 200, resp.text
    assert [s["id"] for s in resp.json()] == [ids[LOC]]


async def test_quoted_location_with_a_comma_combines_with_other_values(client: AsyncClient):
    ids = await _spools(client)

    resp = await client.get(SPOOL, params={"location": f'"{LOC}","Bin 2"'})

    assert resp.status_code == 200, resp.text
    assert sorted(s["id"] for s in resp.json()) == sorted([ids[LOC], ids["Bin 2"]])


async def test_unquoted_comma_still_means_either_value(client: AsyncClient):
    """Existing API behaviour: an unquoted comma separates two fuzzy values."""
    ids = await _spools(client)

    resp = await client.get(SPOOL, params={"location": "Bin 2,Rack 3"})

    assert resp.status_code == 200, resp.text
    assert sorted(s["id"] for s in resp.json()) == sorted([ids["Bin 2"], ids["Rack 3"], ids[LOC]])


async def test_dashboard_card_query_returns_the_group_it_counts(client: AsyncClient):
    """The group header and the card's spool list must agree."""
    ids = await _spools(client)

    groups = (await client.get(GROUP, params={"group_by": "location"})).json()
    card = next(g for g in groups if g["key"] == LOC)
    listed = (await client.get(SPOOL, params={"location": f'"{card["key"]}"'})).json()

    assert card["spool_count"] == 1
    assert [s["id"] for s in listed] == [ids[LOC]]


async def test_quoted_extra_field_value_with_a_comma(client: AsyncClient):
    resp = await client.post("/api/v1/field/spool/shelf", json={"name": "Shelf", "field_type": "text"})
    assert resp.status_code == 200, resp.text
    fil = (await client.post(FIL, json={"density": 1.24, "diameter": 1.75})).json()
    hit = (await client.post(SPOOL, json={"filament_id": fil["id"], "extra": {"shelf": '"A, left"'}})).json()
    await client.post(SPOOL, json={"filament_id": fil["id"], "extra": {"shelf": '"A"'}})

    resp = await client.get(SPOOL, params={"extra.shelf": '"A, left"'})

    assert resp.status_code == 200, resp.text
    assert [s["id"] for s in resp.json()] == [hit["id"]]
