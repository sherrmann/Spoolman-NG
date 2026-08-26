"""LIKE-wildcard escaping for the generic string filters (`?name=`, `?location=`, ...).

`add_where_clause_str`/`add_where_clause_str_opt` (spoolman/database/utils.py) build a fuzzy
`ilike("%<value>%")` for any unquoted filter value. Upstream's audit item 10 escaped LIKE
wildcards in the free-text `search` param and the extra-field filters; this fork has this
additional, separate family of column filters that the same class of bug applies to -- a filter
value of a bare "%" or "_" must not act as a SQL wildcard and match every row.
"""

from httpx import AsyncClient

VENDOR = "/api/v1/vendor"
SPOOL = "/api/v1/spool"
FIL = "/api/v1/filament"


async def test_percent_filter_value_is_matched_literally_not_as_wildcard(client: AsyncClient):
    await client.post(VENDOR, json={"name": "Prusa Research"})
    await client.post(VENDOR, json={"name": "eSUN"})

    resp = await client.get(VENDOR, params={"name": "%"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_underscore_filter_value_is_matched_literally_not_as_wildcard(client: AsyncClient):
    vendor = (await client.post(VENDOR, json={"name": "Prusa Research"})).json()
    pla = (
        await client.post(
            FIL,
            json={"density": 1.24, "diameter": 1.75, "name": "Galaxy Black", "vendor_id": vendor["id"]},
        )
    ).json()
    await client.post(SPOOL, json={"filament_id": pla["id"], "location": "Drybox A"})
    await client.post(SPOOL, json={"filament_id": pla["id"], "location": "Shelf 1"})

    # "_" would otherwise match any single character, i.e. every non-empty location.
    resp = await client.get(SPOOL, params={"location": "_"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_an_ordinary_filter_value_still_matches(client: AsyncClient):
    await client.post(VENDOR, json={"name": "Prusa Research"})
    await client.post(VENDOR, json={"name": "eSUN"})

    resp = await client.get(VENDOR, params={"name": "prusa"})
    assert resp.status_code == 200, resp.text
    assert {v["name"] for v in resp.json()} == {"Prusa Research"}


async def test_a_literal_percent_sign_in_data_can_still_be_found(client: AsyncClient):
    await client.post(VENDOR, json={"name": "100% Recycled Filaments"})
    await client.post(VENDOR, json={"name": "eSUN"})

    resp = await client.get(VENDOR, params={"name": "100%"})
    assert resp.status_code == 200, resp.text
    assert {v["name"] for v in resp.json()} == {"100% Recycled Filaments"}
