"""GET /spool/group?include_empty=true: filaments with no spools as groups of zero (#444).

Grouping aggregates over spools, so a filament nobody owns a spool of can never produce a
group and vanishes from the list -- which reads as "in stock" when it means the opposite
(upstream issue 1092). The Svelte library's "Show filaments with no spools" sends
include_empty; upstream added it in 33ad8d71 and folded it into find_groups in 6dce8717.
Only the client half reached this fork, so the flag was ignored.

Ported from upstream's tests_integration/tests/spool/test_group.py, minus the date filters
this fork's group endpoint does not have.
"""

import json
from dataclasses import dataclass

import pytest
from httpx import AsyncClient

GROUP = "/api/v1/spool/group"
FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"


@dataclass
class Fixture:
    stocked_id: int
    empty_id: int
    archived_only_id: int

    @property
    def ids(self) -> str:
        """All three filament ids, as a `filament.id` filter value."""
        return f"{self.stocked_id},{self.empty_id},{self.archived_only_id}"


async def _seed(client: AsyncClient) -> Fixture:
    """Three filaments of one vendor: one stocked, one with only an archived spool, one with none."""
    vendor = (await client.post("/api/v1/vendor", json={"name": "Acme"})).json()
    ids = []
    for name, material in (("Stocked", "PLA"), ("Empty", "ABS"), ("ArchivedOnly", "PETG")):
        resp = await client.post(
            FIL,
            json={
                "name": name,
                "vendor_id": vendor["id"],
                "material": material,
                "density": 1.25,
                "diameter": 1.75,
                "weight": 1000,
            },
        )
        assert resp.status_code == 200, resp.text
        ids.append(resp.json()["id"])
    stocked, empty, archived_only = ids
    for payload in (
        {"filament_id": stocked, "remaining_weight": 1000, "location": "Shelf A"},
        {"filament_id": stocked, "remaining_weight": 400, "location": "Shelf B"},
        {"filament_id": archived_only, "remaining_weight": 900, "archived": True},
    ):
        resp = await client.post(SPOOL, json=payload)
        assert resp.status_code == 200, resp.text
    return Fixture(stocked, empty, archived_only)


def _by_key(groups: list[dict]) -> dict[str, dict]:
    return {g["key"]: g for g in groups}


async def test_omits_empty_filaments_by_default(client: AsyncClient):
    f = await _seed(client)

    resp = await client.get(GROUP, params={"group_by": "filament", "filament.id": f.ids})

    assert resp.status_code == 200, resp.text
    assert resp.headers["x-total-count"] == "1"
    assert _by_key(resp.json()).keys() == {str(f.stocked_id)}


async def test_include_empty_lists_filaments_with_no_spools_as_zero(client: AsyncClient):
    f = await _seed(client)

    resp = await client.get(GROUP, params={"group_by": "filament", "filament.id": f.ids, "include_empty": "true"})

    assert resp.status_code == 200, resp.text
    assert resp.headers["x-total-count"] == "3"
    groups = _by_key(resp.json())
    assert groups[str(f.stocked_id)]["spool_count"] == 2
    assert groups[str(f.stocked_id)]["total_remaining_weight"] == pytest.approx(1400)
    for filament_id in (f.empty_id, f.archived_only_id):
        group = groups[str(filament_id)]
        assert group["spool_count"] == 0
        assert group["in_use_count"] == 0
        assert group["total_remaining_weight"] == pytest.approx(0)
        # Hydrated like a populated group, so the client draws the same header for it.
        assert group["filament"]["id"] == filament_id
        # Never used: no timestamp, rather than a zero one.
        assert "last_used" not in group


async def test_include_empty_respects_allow_archived(client: AsyncClient):
    f = await _seed(client)

    resp = await client.get(
        GROUP,
        params={"group_by": "filament", "filament.id": f.ids, "include_empty": "true", "allow_archived": "true"},
    )

    groups = _by_key(resp.json())
    assert groups[str(f.archived_only_id)]["spool_count"] == 1
    assert groups[str(f.empty_id)]["spool_count"] == 0


async def test_include_empty_applies_filament_filters(client: AsyncClient):
    f = await _seed(client)

    resp = await client.get(
        GROUP,
        params={"group_by": "filament", "filament.id": f.ids, "filament.material": '"ABS"', "include_empty": "true"},
    )

    assert resp.headers["x-total-count"] == "1"
    assert [(g["key"], g["spool_count"]) for g in resp.json()] == [(str(f.empty_id), 0)]


async def test_include_empty_sorts_and_pages_over_all_groups(client: AsyncClient):
    f = await _seed(client)
    params = {
        "group_by": "filament",
        "filament.id": f.ids,
        "include_empty": "true",
        "sort": "group.spool_count:desc",
    }

    resp = await client.get(GROUP, params=params)
    assert [g["spool_count"] for g in resp.json()] == [2, 0, 0]

    seen: list[str] = []
    for offset in (0, 2):
        page = await client.get(GROUP, params={**params, "limit": 2, "offset": offset})
        assert page.headers["x-total-count"] == "3"
        seen += [g["key"] for g in page.json()]
    assert sorted(seen) == sorted(str(i) for i in (f.stocked_id, f.empty_id, f.archived_only_id))


async def test_include_empty_applies_filament_extra_field_filters(client: AsyncClient):
    """No spool to go through: the filament has to answer its extra-field filter itself."""
    resp = await client.post("/api/v1/field/filament/grade", json={"name": "Grade", "field_type": "text"})
    assert resp.status_code == 200, resp.text
    ids = []
    for grade in ("Premium", "Standard"):
        resp = await client.post(
            FIL, json={"name": grade, "density": 1.25, "diameter": 1.75, "extra": {"grade": json.dumps(grade)}}
        )
        ids.append(resp.json()["id"])

    without = await client.get(GROUP, params={"group_by": "filament", "filament.extra.grade": '"Premium"'})
    with_empty = await client.get(
        GROUP, params={"group_by": "filament", "filament.extra.grade": '"Premium"', "include_empty": "true"}
    )

    assert without.json() == []
    assert with_empty.headers["x-total-count"] == "1"
    assert [(g["key"], g["spool_count"]) for g in with_empty.json()] == [(str(ids[0]), 0)]


async def test_include_empty_rejected_for_other_group_by(client: AsyncClient):
    for group_by in ("vendor", "material", "location"):
        resp = await client.get(GROUP, params={"group_by": group_by, "include_empty": "true"})
        assert resp.status_code == 400, group_by


async def test_include_empty_rejected_with_spool_level_filters(client: AsyncClient):
    """Filaments with no spools AND a filter on the spools is a contradiction, so it is refused."""
    f = await _seed(client)
    for params in ({"location": '"Shelf A"'}, {"lot_nr": '"B12"'}):
        resp = await client.get(GROUP, params={"group_by": "filament", "include_empty": "true", **params})
        assert resp.status_code == 400, params

    await client.post("/api/v1/field/spool/opened", json={"name": "Opened", "field_type": "text"})
    resp = await client.get(GROUP, params={"group_by": "filament", "include_empty": "true", "extra.opened": '"yes"'})
    assert resp.status_code == 400

    # Archiving is the exception: a filament whose every spool is archived has none to print with.
    resp = await client.get(GROUP, params={"group_by": "filament", "include_empty": "true", "filament.id": f.ids})
    assert _by_key(resp.json())[str(f.archived_only_id)]["spool_count"] == 0
