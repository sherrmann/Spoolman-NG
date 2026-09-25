"""Searching and paging through the external filament catalog (GET /external/filament/search).

The vendored Svelte client searches the catalog server-side from Add Spool and Change
Filament. Upstream added the endpoint with the client (ed758a11) and paging later
(feb67ab5); only the client halves reached this fork, so the call was a 404 (#443). This
fork's catalog is SpoolmanDB and TigerTag merged, so the search covers both.
"""

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spoolman import filecache
from spoolman.api.v1 import externaldb


def filament(i: int, manufacturer: str, name: str, material: str = "PLA") -> dict:
    return {
        "id": f"filament_{i}",
        "manufacturer": manufacturer,
        "name": name,
        "material": material,
        "density": 1.24,
        "weight": 1000,
        "diameter": 1.75,
    }


@pytest.fixture(autouse=True)
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    rows = [filament(i, "Elegoo", f"White {i}") for i in range(25)]
    rows.insert(10, filament(100, "Polymaker", "PolyLite Black", "PETG"))
    spoolmandb = tmp_path / "filaments.json"
    spoolmandb.write_text(json.dumps(rows))
    tigertag = tmp_path / "tigertag.json"
    tigertag.write_text(json.dumps([filament(200, "Rosa3D", "Silk Gold", "PLA")]))
    monkeypatch.setattr(externaldb, "get_filaments_file", lambda: spoolmandb)
    monkeypatch.setattr(externaldb, "get_tigertag_filaments_file", lambda: tigertag)
    monkeypatch.setattr(externaldb, "is_tigertag_enabled", lambda: True)
    monkeypatch.setattr(externaldb, "_catalog_cache", None)
    return {"spoolmandb": spoolmandb, "tigertag": tigertag}


def test_pages_cover_every_match_once_in_catalog_order():
    ids = []
    for offset in (0, 10, 20):
        items, total = externaldb.search_filaments("elegoo white", limit=10, offset=offset)
        assert total == 25
        ids += [f.id for f in items]
    assert ids == [f"filament_{i}" for i in range(25)]


def test_an_offset_past_the_end_is_empty_but_still_counts():
    assert externaldb.search_filaments("elegoo", limit=10, offset=30) == ([], 25)


def test_every_word_must_match_case_insensitively():
    items, total = externaldb.search_filaments("POLYMAKER petg", limit=10)
    assert ([f.id for f in items], total) == (["filament_100"], 1)


def test_a_blank_query_matches_nothing():
    assert externaldb.search_filaments("   ", limit=10) == ([], 0)


def test_tigertag_entries_are_searched_and_marked_with_their_source():
    items, total = externaldb.search_filaments("rosa3d silk", limit=10)
    assert total == 1
    assert (items[0].id, items[0].source) == ("filament_200", "tigertag")


def test_tigertag_is_left_out_when_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(externaldb, "is_tigertag_enabled", lambda: False)
    assert externaldb.search_filaments("rosa3d", limit=10) == ([], 0)


def test_a_rewritten_catalog_is_picked_up(catalog: dict[str, Path]):
    assert externaldb.search_filaments("fiberlogy", limit=10)[1] == 0
    catalog["spoolmandb"].write_text(json.dumps([filament(300, "Fiberlogy", "Easy PLA", "PLA") | {"x": "pad"}]))

    items, total = externaldb.search_filaments("fiberlogy", limit=10)

    assert (total, [f.id for f in items]) == (1, ["filament_300"])


def test_entries_synced_with_a_null_source_are_labelled(catalog: dict[str, Path]):
    """The synced SpoolmanDB file stores "source": null on every entry; it must still be labelled."""
    catalog["spoolmandb"].write_text(json.dumps([filament(1, "Elegoo", "White 1") | {"source": None}]))

    items, _ = externaldb.search_filaments("elegoo", limit=10)

    assert items[0].source == "spoolmandb"


def test_a_malformed_entry_is_skipped_not_fatal(catalog: dict[str, Path]):
    rows = [filament(1, "Elegoo", "White 1"), {"id": "broken", "manufacturer": "Elegoo"}]
    catalog["spoolmandb"].write_text(json.dumps(rows))

    items, total = externaldb.search_filaments("elegoo", limit=10)

    assert (total, [f.id for f in items]) == (1, ["filament_1"])


async def test_endpoint_returns_the_page_and_the_total_count():
    app = FastAPI()
    app.include_router(externaldb.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/external/filament/search", params={"query": "elegoo", "limit": 8})
        page2 = await client.get("/external/filament/search", params={"query": "elegoo", "limit": 8, "offset": 8})
        too_big = await client.get("/external/filament/search", params={"query": "elegoo", "limit": 101})

    assert resp.status_code == 200, resp.text
    assert resp.headers["x-total-count"] == "25"
    assert [f["id"] for f in resp.json()] == [f"filament_{i}" for i in range(8)]
    assert [f["id"] for f in page2.json()] == [f"filament_{i}" for i in range(8, 16)]
    assert too_big.status_code == 422


def test_a_same_size_rewrite_within_the_same_second_is_picked_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The sync can rewrite the catalog with the same size and, on a coarse filesystem, the same mtime."""
    monkeypatch.setattr(filecache, "get_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(externaldb, "get_filaments_file", lambda: filecache.get_file("filaments.json"))
    monkeypatch.setattr(externaldb, "is_tigertag_enabled", lambda: False)
    first = json.dumps([filament(1, "Aaaaaa", "Black")]).encode()
    second = json.dumps([filament(1, "Bbbbbb", "Black")]).encode()
    assert len(first) == len(second)

    filecache.update_file("filaments.json", first)
    stamp = filecache.get_file("filaments.json").stat()
    assert externaldb.search_filaments("aaaaaa", limit=10)[1] == 1

    filecache.update_file("filaments.json", second)
    os.utime(filecache.get_file("filaments.json"), ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    assert externaldb.search_filaments("aaaaaa", limit=10)[1] == 0
    assert externaldb.search_filaments("bbbbbb", limit=10)[1] == 1
