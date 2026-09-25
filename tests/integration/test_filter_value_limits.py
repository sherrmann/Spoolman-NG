"""Filters with very many values: answered, or refused with a 400, never a 500.

SQLite parses `a OR b OR c ...` into a tree as deep as the chain is long and refuses one deeper
than 1000, so a filter with about a thousand values raised "Expression tree is too large" as a
500. Exact matches on a built-in field now share one IN list, which does not nest, so any number
of them works; a chain of alternatives that cannot be merged is capped on SQLite with a 400.
"""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import column

from spoolman import env
from spoolman.database.utils import SQLITE_MAX_FILTER_ALTERNATIVES, any_of

SPOOL = "/api/v1/spool"
FIL = "/api/v1/filament"
MANY = 3000


async def _spools(client: AsyncClient) -> dict[str, int]:
    vendor = (await client.post("/api/v1/vendor", json={"name": "Acme"})).json()
    ids = {}
    for location in ("Shelf A", "Shelf B"):
        fil = (await client.post(FIL, json={"density": 1.24, "diameter": 1.75, "vendor_id": vendor["id"]})).json()
        spool = await client.post(SPOOL, json={"filament_id": fil["id"], "location": location})
        ids[location] = spool.json()["id"]
    return ids


def _exact(values: list[str]) -> str:
    return ",".join(f'"{v}"' for v in values)


async def test_thousands_of_exact_values_are_answered(client: AsyncClient):
    ids = await _spools(client)
    decoys = [f"Nowhere {i}" for i in range(MANY)]

    resp = await client.get(SPOOL, params={"location": _exact([*decoys, "Shelf B"])})
    grouped = await client.get(
        f"{SPOOL}/group", params={"group_by": "location", "location": _exact([*decoys, "Shelf B"])}
    )

    assert resp.status_code == 200, resp.text
    assert [s["id"] for s in resp.json()] == [ids["Shelf B"]]
    assert grouped.status_code == 200, grouped.text
    assert [g["key"] for g in grouped.json()] == ["Shelf B"]


async def test_exact_values_still_combine_with_empty_and_substring_ones(client: AsyncClient):
    ids = await _spools(client)
    no_location = (await client.post(SPOOL, json={"filament_id": 1})).json()["id"]

    resp = await client.get(SPOOL, params={"location": '"Shelf A",,elf B'})

    assert sorted(s["id"] for s in resp.json()) == sorted([ids["Shelf A"], ids["Shelf B"], no_location])


async def test_thousands_of_vendor_ids_are_answered(client: AsyncClient):
    await _spools(client)
    vendor_id = (await client.get("/api/v1/vendor")).json()[0]["id"]
    others = [str(i) for i in range(10_000, 10_000 + MANY)]

    resp = await client.get(SPOOL, params={"filament.vendor.id": ",".join([*others, str(vendor_id), "-1"])})

    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2


@pytest.mark.parametrize(
    ("url", "param", "more"),
    [
        (SPOOL, "location", {}),
        (SPOOL, "filament.name", {}),
        (SPOOL, "search", {}),
        (f"{SPOOL}/group", "filament.material", {"group_by": "filament"}),
        (FIL, "name", {}),
        (FIL, "search", {}),
        ("/api/v1/vendor", "name", {}),
    ],
)
async def test_thousands_of_substring_values_are_refused_with_a_400(
    client: AsyncClient, url: str, param: str, more: dict
):
    resp = await client.get(url, params={param: ",".join(f"x{i}" for i in range(MANY)), **more})

    assert resp.status_code == 400, resp.text
    assert "too many alternatives" in resp.json()["message"]


async def test_thousands_of_extra_field_values_are_refused_with_a_400(client: AsyncClient):
    await client.post("/api/v1/field/spool/bin", json={"name": "Bin", "field_type": "text"})

    resp = await client.get(SPOOL, params={"extra.bin": ",".join(json.dumps(f"b{i}") for i in range(MANY))})

    assert resp.status_code == 400, resp.text
    assert "extra.bin" in resp.json()["message"]


def test_the_cap_applies_to_sqlite_only(monkeypatch: pytest.MonkeyPatch):
    """Postgres, MariaDB and CockroachDB parse a long OR chain without a depth limit."""
    conditions = [column("x") == i for i in range(SQLITE_MAX_FILTER_ALTERNATIVES + 1)]

    for db_type in (None, env.DatabaseType.SQLITE):
        monkeypatch.setattr(env, "get_database_type", lambda db_type=db_type: db_type)
        with pytest.raises(ValueError, match="too many alternatives"):
            any_of(conditions, "x")

    for db_type in (env.DatabaseType.POSTGRES, env.DatabaseType.MYSQL, env.DatabaseType.COCKROACHDB):
        monkeypatch.setattr(env, "get_database_type", lambda db_type=db_type: db_type)
        any_of(conditions, "x")


async def test_a_long_search_still_works_on_sqlite(client: AsyncClient):
    """Each search term is eight alternatives; SQLite itself accepted about 124 terms before the cap."""
    resp = await client.get(SPOOL, params={"search": ",".join(f"w{i}" for i in range(100))})
    assert resp.status_code == 200, resp.text
