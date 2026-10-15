"""Integration tests for GET /spool/group catalogue views on every supported database.

Ported from upstream's tests_integration/tests/spool/test_group.py (02f5c07c1, 30928407a): the
group.vendor_name sort, include_empty for group_by=vendor, filament_count, preview=true, the
X-Total-Spools / X-Total-Remaining-Weight headers, and the filament.*, filament.vendor.* and
extra-field sort keys. The only assertion dropped is the `registered` date filter in the vendor
include_empty rejection test, because this fork's group endpoint has no first_used/last_used/
registered filters.
"""

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from ..conftest import URL


def _group_by_key(groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {group["key"]: group for group in groups}


# --- Vendor groups, manufacturer sorting, previews and totals -----------------------------------
# These back the client's filament and manufacturer lists: filaments paged in manufacturer sections,
# manufacturers with their filament counts, a few pips/swatches per group, and list-wide totals.


@dataclass
class VendorFixture:
    vendor_a: int  # two filaments: a1 (6 spools + 1 archived) and a2 (no spools)
    vendor_b: int  # one filament: b1 (1 spool + 1 archived)
    vendor_c: int  # no filaments at all
    a1: int
    a2: int
    b1: int
    none1: int  # filament with no manufacturer, 1 spool
    a1_spool_ids: list[int]  # non-archived, ascending
    a1_archived_spool_id: int
    b1_archived_spool_id: int
    spool_ids: list[int]

    @property
    def vendor_ids(self) -> str:
        """The three vendors, as a filter value."""
        return f"{self.vendor_a},{self.vendor_b},{self.vendor_c}"

    @property
    def filament_ids(self) -> str:
        """The four filaments, as a filter value."""
        return f"{self.a1},{self.a2},{self.b1},{self.none1}"


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = httpx.post(f"{URL}/api/v1/{path}", json=payload)
    result.raise_for_status()
    return result.json()


def _filament(name: str, vendor_id: int | None, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    payload = {"name": name, "material": "PLA", "density": 1.25, "diameter": 1.75, "weight": 1000, **extra}
    if vendor_id is not None:
        payload["vendor_id"] = vendor_id
    return _post("filament", payload)


@pytest.fixture(scope="module")
def vendor_groups() -> Iterable[VendorFixture]:
    """Vendors A < B < C by name, with the filaments and spools described on VendorFixture."""
    tag = uuid.uuid4().hex[:8]
    vendor_ids = [_post("vendor", {"name": f"{tag}-{letter}"})["id"] for letter in "ABC"]
    vendor_a, vendor_b, vendor_c = vendor_ids
    a1 = _filament(f"{tag}-a1", vendor_a)["id"]
    a2 = _filament(f"{tag}-a2", vendor_a)["id"]
    b1 = _filament(f"{tag}-b1", vendor_b)["id"]
    none1 = _filament(f"{tag}-none", None)["id"]

    a1_spool_ids = [_post("spool", {"filament_id": a1, "remaining_weight": 500})["id"] for _ in range(6)]
    a1_archived = _post("spool", {"filament_id": a1, "remaining_weight": 1000, "archived": True})["id"]
    b1_spool = _post("spool", {"filament_id": b1, "remaining_weight": 200})["id"]
    b1_archived = _post("spool", {"filament_id": b1, "remaining_weight": 100, "archived": True})["id"]
    none_spool = _post("spool", {"filament_id": none1, "remaining_weight": 200})["id"]
    spool_ids = [*a1_spool_ids, a1_archived, b1_spool, b1_archived, none_spool]

    yield VendorFixture(
        vendor_a=vendor_a,
        vendor_b=vendor_b,
        vendor_c=vendor_c,
        a1=a1,
        a2=a2,
        b1=b1,
        none1=none1,
        a1_spool_ids=a1_spool_ids,
        a1_archived_spool_id=a1_archived,
        b1_archived_spool_id=b1_archived,
        spool_ids=spool_ids,
    )

    for spool_id in spool_ids:
        httpx.delete(f"{URL}/api/v1/spool/{spool_id}").raise_for_status()
    for filament_id in (a1, a2, b1, none1):
        httpx.delete(f"{URL}/api/v1/filament/{filament_id}").raise_for_status()
    for vendor_id in vendor_ids:
        httpx.delete(f"{URL}/api/v1/vendor/{vendor_id}").raise_for_status()


def _groups(params: dict[str, Any]) -> httpx.Response:
    result = httpx.get(f"{URL}/api/v1/spool/group", params=params)
    result.raise_for_status()
    return result


def test_group_sort_vendor_name_orders_by_manufacturer_with_vendorless_last(vendor_groups: VendorFixture):
    """group.vendor_name sections filament groups by manufacturer; no manufacturer goes last, both ways."""
    f = vendor_groups
    expected = [f.a1, f.a2, f.b1, f.none1]
    params = {"group_by": "filament", "filament.id": f.filament_ids, "include_empty": "true"}
    result = _groups({**params, "sort": "group.vendor_name:asc,group.title:asc"})
    assert [int(g["key"]) for g in result.json()] == expected

    # Descending flips the manufacturers but the vendorless filament still sinks to the bottom.
    result = _groups({**params, "sort": "group.vendor_name:desc,group.title:asc"})
    assert [int(g["key"]) for g in result.json()] == [f.b1, f.a1, f.a2, f.none1]

    # Paging with the boundary between the two vendors in the middle of the page break.
    first = _groups({**params, "sort": "group.vendor_name:asc,group.title:asc", "limit": 2, "offset": 0})
    second = _groups({**params, "sort": "group.vendor_name:asc,group.title:asc", "limit": 2, "offset": 2})
    assert first.headers["x-total-count"] == "4"
    assert [int(g["key"]) for g in first.json()] == expected[:2]
    assert [int(g["key"]) for g in second.json()] == expected[2:]


def test_group_by_vendor_sorted_by_vendor_name(vendor_groups: VendorFixture):
    """The sort key is valid on the vendor axis itself too."""
    f = vendor_groups
    result = _groups(
        {
            "group_by": "vendor",
            "filament.vendor.id": f.vendor_ids,
            "include_empty": "true",
            "sort": "group.vendor_name:desc",
        },
    )
    assert [int(g["key"]) for g in result.json()] == [f.vendor_c, f.vendor_b, f.vendor_a]


def test_group_by_vendor_include_empty(vendor_groups: VendorFixture):
    """A manufacturer with no filaments is a group of zeros; filament_count counts all its filaments."""
    f = vendor_groups
    params = {"group_by": "vendor", "filament.vendor.id": f.vendor_ids}

    plain = _group_by_key(_groups(params).json())
    assert plain.keys() == {str(f.vendor_a), str(f.vendor_b)}
    # Spool-driven: only the filaments that have a matching spool count.
    assert plain[str(f.vendor_a)]["filament_count"] == 1
    assert plain[str(f.vendor_b)]["filament_count"] == 1

    result = _groups({**params, "include_empty": "true"})
    assert result.headers["x-total-count"] == "3"
    groups = _group_by_key(result.json())
    assert groups[str(f.vendor_a)]["filament_count"] == 2
    assert groups[str(f.vendor_a)]["spool_count"] == 6  # archived excluded
    assert groups[str(f.vendor_a)]["total_remaining_weight"] == pytest.approx(3000)
    assert groups[str(f.vendor_b)]["filament_count"] == 1
    empty = groups[str(f.vendor_c)]
    assert empty["spool_count"] == 0
    assert empty["in_use_count"] == 0
    assert empty["total_remaining_weight"] == 0
    assert empty["filament_count"] == 0
    assert empty["vendor"]["id"] == f.vendor_c
    assert "last_used" not in empty

    # allow_archived rides in the join, so nothing disappears and the counts grow.
    result = _groups({**params, "include_empty": "true", "allow_archived": "true"})
    groups = _group_by_key(result.json())
    assert groups[str(f.vendor_a)]["spool_count"] == 7
    assert groups[str(f.vendor_c)]["spool_count"] == 0

    # A filament-level filter applies as a WHERE: only manufacturers with a matching filament remain.
    result = _groups({**params, "include_empty": "true", "filament.id": str(f.a2)})
    groups = _group_by_key(result.json())
    assert groups.keys() == {str(f.vendor_a)}
    assert groups[str(f.vendor_a)]["filament_count"] == 1
    assert groups[str(f.vendor_a)]["spool_count"] == 0

    # The vendor-less filament's group is not listed: this mode lists manufacturers.
    result = _groups({"group_by": "vendor", "include_empty": "true", "filament.id": str(f.none1)})
    assert result.json() == []


def test_group_by_vendor_include_empty_rejections():
    """Spool-scoped filters stay a 400 for vendors, and other axes still are."""
    for params in ({"location": '"Shelf A"'}, {"lot_nr": '"B12"'}):
        result = httpx.get(
            f"{URL}/api/v1/spool/group",
            params={"group_by": "vendor", "include_empty": "true", **params},
        )
        assert result.status_code == 400, params
    for group_by in ("material", "location"):
        result = httpx.get(f"{URL}/api/v1/spool/group", params={"group_by": group_by, "include_empty": "true"})
        assert result.status_code == 400, group_by


def test_group_by_filament_has_no_filament_count(vendor_groups: VendorFixture):
    """filament_count belongs to vendor groups only."""
    result = _groups({"group_by": "filament", "filament.id": str(vendor_groups.a1)})
    assert "filament_count" not in result.json()[0]


def test_group_preview_spools_for_filament_groups(vendor_groups: VendorFixture):
    """A filament group previews up to 5 of exactly the spools its spool_count counted, by id."""
    f = vendor_groups
    params = {"group_by": "filament", "filament.id": f"{f.a1},{f.b1},{f.a2}", "include_empty": "true"}

    assert all("spools" not in g for g in _groups(params).json())

    groups = _group_by_key(_groups({**params, "preview": "true"}).json())
    a1 = groups[str(f.a1)]
    assert a1["spool_count"] == 6
    assert [s["id"] for s in a1["spools"]] == f.a1_spool_ids[:5]
    assert a1["spools"][0] == {"id": f.a1_spool_ids[0], "remaining_weight": 500, "initial_weight": 1000}
    assert groups[str(f.a2)]["spools"] == []  # an empty group previews as empty, not as absent
    b1 = groups[str(f.b1)]
    assert [s["remaining_weight"] for s in b1["spools"]] == [200]  # archived spool excluded

    groups = _group_by_key(_groups({**params, "preview": "true", "allow_archived": "true"}).json())
    b1 = groups[str(f.b1)]
    assert b1["spool_count"] == 2
    assert [s["id"] for s in b1["spools"]][-1] == f.b1_archived_spool_id
    assert len(b1["spools"]) == b1["spool_count"]
    assert len(groups[str(f.a1)]["spools"]) == 5


def test_group_preview_spools_follow_spool_filters(vendor_groups: VendorFixture):
    """Spool-level filters reach the preview, so it never shows a spool the group did not count."""
    f = vendor_groups
    target = f.a1_spool_ids[2]
    httpx.patch(f"{URL}/api/v1/spool/{target}", json={"location": f"pv-{uuid.uuid4().hex[:8]}"}).raise_for_status()
    try:
        location = httpx.get(f"{URL}/api/v1/spool/{target}").json()["location"]
        result = _groups(
            {"group_by": "filament", "filament.id": str(f.a1), "location": f'"{location}"', "preview": "true"},
        )
        group = result.json()[0]
        assert group["spool_count"] == 1
        assert [s["id"] for s in group["spools"]] == [target]
    finally:
        httpx.patch(f"{URL}/api/v1/spool/{target}", json={"location": ""}).raise_for_status()


def test_group_preview_filaments_for_vendor_groups():
    """A vendor group previews up to 4 of its filaments, by name, with their colors."""
    tag = uuid.uuid4().hex[:8]
    vendor_id = _post("vendor", {"name": f"{tag}-many"})["id"]
    filaments = [
        _filament(
            f"{tag}-f{i}",
            vendor_id,
            **(
                {"multi_color_hexes": "FF0000,00FF00", "multi_color_direction": "coaxial"}
                if i == 0
                else {"color_hex": "0000FF"}
            ),
        )
        for i in range(5)
    ]
    # The only spool is on the LAST filament: the preview still shows the manufacturer's first four,
    # while filament_count says how many actually hold stock.
    spool_id = _post("spool", {"filament_id": filaments[4]["id"], "remaining_weight": 100})["id"]
    try:
        params = {"group_by": "vendor", "filament.vendor.id": str(vendor_id)}
        assert "filaments" not in _groups(params).json()[0]
        for extra in ({}, {"include_empty": "true"}):
            group = _groups({**params, **extra, "preview": "true"}).json()[0]
            assert [x["id"] for x in group["filaments"]] == [x["id"] for x in filaments[:4]]
            assert group["filaments"][0]["multi_color_hexes"] == "FF0000,00FF00"
            assert group["filaments"][0]["multi_color_direction"] == "coaxial"
            assert group["filaments"][1] == {"id": filaments[1]["id"], "color_hex": "0000FF"}
            assert "spools" not in group
        assert _groups({**params, "preview": "true"}).json()[0]["filament_count"] == 1
        assert _groups({**params, "preview": "true", "include_empty": "true"}).json()[0]["filament_count"] == 5
    finally:
        httpx.delete(f"{URL}/api/v1/spool/{spool_id}").raise_for_status()
        for filament in filaments:
            httpx.delete(f"{URL}/api/v1/filament/{filament['id']}").raise_for_status()
        httpx.delete(f"{URL}/api/v1/vendor/{vendor_id}").raise_for_status()


def test_group_preview_ignored_for_other_axes(vendor_groups: VendorFixture):
    """Material/location groups have no members to preview."""
    for group_by in ("material", "location"):
        result = _groups({"group_by": group_by, "filament.id": vendor_groups.filament_ids, "preview": "true"})
        assert result.json()
        assert all("spools" not in g and "filaments" not in g for g in result.json())


def test_group_total_headers(vendor_groups: VendorFixture):
    """x-total-spools / x-total-remaining-weight sum every matching group, not just the page."""
    f = vendor_groups
    params = {"group_by": "filament", "filament.id": f.filament_ids}
    result = _groups({**params, "limit": 1})
    assert len(result.json()) == 1
    assert result.headers["x-total-count"] == "3"
    assert result.headers["x-total-spools"] == "8"  # 6 + 1 + 1, archived excluded
    assert float(result.headers["x-total-remaining-weight"]) == pytest.approx(3400)

    result = _groups({**params, "include_empty": "true", "limit": 1})
    assert result.headers["x-total-count"] == "4"
    assert result.headers["x-total-spools"] == "8"  # empty groups add groups, not spools
    assert float(result.headers["x-total-remaining-weight"]) == pytest.approx(3400)

    result = _groups({**params, "allow_archived": "true"})
    assert result.headers["x-total-spools"] == "10"
    assert float(result.headers["x-total-remaining-weight"]) == pytest.approx(4500)

    # No matching groups at all: zeros, not a missing header or "None".
    result = _groups({"group_by": "filament", "filament.id": "999999999"})
    assert result.headers["x-total-count"] == "0"
    assert result.headers["x-total-spools"] == "0"
    assert float(result.headers["x-total-remaining-weight"]) == 0


# --- sorting groups by filament / manufacturer columns and extra fields ----


def _group_keys(params: dict[str, str]) -> list[str]:
    result = httpx.get(f"{URL}/api/v1/spool/group", params=params)
    result.raise_for_status()
    return [group["key"] for group in result.json()]


def _post_filament(vendor_id: int | None, **fields: float | dict[str, str]) -> int:
    payload = {"name": f"Sort-{uuid.uuid4().hex[:8]}", "density": 1.25, "diameter": 1.75, "weight": 1000, **fields}
    if vendor_id is not None:
        payload["vendor_id"] = vendor_id
    result = httpx.post(f"{URL}/api/v1/filament", json=payload)
    result.raise_for_status()
    return result.json()["id"]


@dataclass
class SortFixture:
    vendor_ids: list[int]  # empty_spool_weight 300, 100, unset (no filaments)
    filament_ids: list[int]  # temps 210, 190, unset; "n" extra 10, 9, unset
    int_key: str
    vendor_key: str


@pytest.fixture(scope="module")
def sort_fixture() -> Iterable[SortFixture]:
    """Three vendors (the last without filaments) and three filaments, each with a NULL somewhere."""
    suffix = uuid.uuid4().hex[:8]
    int_key = f"n_{suffix}"
    vendor_key = f"v_{suffix}"
    httpx.post(f"{URL}/api/v1/field/filament/{int_key}", json={"name": "N", "field_type": "integer"}).raise_for_status()
    httpx.post(f"{URL}/api/v1/field/vendor/{vendor_key}", json={"name": "V", "field_type": "text"}).raise_for_status()

    vendor_ids: list[int] = []
    for name, weight, extra in (("B", 300, "zeta"), ("A", 100, "alpha"), ("C", None, None)):
        payload: dict[str, Any] = {"name": f"{name}-{suffix}"}
        if weight is not None:
            payload["empty_spool_weight"] = weight
        if extra is not None:
            payload["extra"] = {vendor_key: json.dumps(extra)}
        result = httpx.post(f"{URL}/api/v1/vendor", json=payload)
        result.raise_for_status()
        vendor_ids.append(result.json()["id"])

    filament_ids = [
        _post_filament(vendor_ids[0], settings_extruder_temp=210, extra={int_key: json.dumps(10)}),
        _post_filament(vendor_ids[1], settings_extruder_temp=190, extra={int_key: json.dumps(9)}),
        _post_filament(vendor_ids[1]),
    ]
    spool_ids = []
    for filament_id, weights in zip(filament_ids, ([500, 300], [100], []), strict=True):
        for weight in weights:
            result = httpx.post(f"{URL}/api/v1/spool", json={"filament_id": filament_id, "remaining_weight": weight})
            result.raise_for_status()
            spool_ids.append(result.json()["id"])

    yield SortFixture(vendor_ids=vendor_ids, filament_ids=filament_ids, int_key=int_key, vendor_key=vendor_key)

    for spool_id in spool_ids:
        httpx.delete(f"{URL}/api/v1/spool/{spool_id}")
    for filament_id in filament_ids:
        httpx.delete(f"{URL}/api/v1/filament/{filament_id}")
    for vendor_id in vendor_ids:
        httpx.delete(f"{URL}/api/v1/vendor/{vendor_id}")
    httpx.delete(f"{URL}/api/v1/field/filament/{int_key}")
    httpx.delete(f"{URL}/api/v1/field/vendor/{vendor_key}")


def _fil_params(fx: SortFixture, sort: str, **extra: str) -> dict[str, str]:
    return {
        "group_by": "filament",
        "filament.id": ",".join(str(i) for i in fx.filament_ids),
        "include_empty": "true",
        "sort": sort,
        **extra,
    }


def _ids(keys: list[int]) -> list[str]:
    return [str(k) for k in keys]


def test_sort_by_filament_column_nulls_last(sort_fixture: SortFixture):
    a, b, c = sort_fixture.filament_ids
    asc = _group_keys(_fil_params(sort_fixture, "filament.settings_extruder_temp:asc"))
    desc = _group_keys(_fil_params(sort_fixture, "filament.settings_extruder_temp:desc"))
    assert asc == _ids([b, a, c])
    assert desc == _ids([a, b, c])


def test_sort_by_vendor_column_for_vendor_groups(sort_fixture: SortFixture):
    v300, v100, _v_none = sort_fixture.vendor_ids
    params = {
        "group_by": "vendor",
        "include_empty": "true",
        "filament.vendor.id": ",".join(str(i) for i in sort_fixture.vendor_ids),
    }
    asc = _group_keys({**params, "sort": "filament.vendor.empty_spool_weight:asc"})
    desc = _group_keys({**params, "sort": "filament.vendor.empty_spool_weight:desc"})
    assert asc[:2] == _ids([v100, v300])
    assert desc[:2] == _ids([v300, v100])


def test_sort_by_vendor_column_includes_filamentless_vendor_last(sort_fixture: SortFixture):
    v300, v100, v_none = sort_fixture.vendor_ids
    result = httpx.get(
        f"{URL}/api/v1/spool/group",
        params={"group_by": "vendor", "include_empty": "true", "sort": "filament.vendor.empty_spool_weight:asc"},
    )
    result.raise_for_status()
    keys = [g["key"] for g in result.json() if g["key"] in _ids(sort_fixture.vendor_ids)]
    assert keys == _ids([v100, v300, v_none])


def test_sort_by_integer_extra_field_is_numeric(sort_fixture: SortFixture):
    a, b, c = sort_fixture.filament_ids  # 10, 9, unset
    key = f"filament.extra.{sort_fixture.int_key}"
    assert _group_keys(_fil_params(sort_fixture, f"{key}:asc")) == _ids([b, a, c])
    assert _group_keys(_fil_params(sort_fixture, f"{key}:desc")) == _ids([a, b, c])


def test_sort_by_vendor_extra_field(sort_fixture: SortFixture):
    key = f"filament.vendor.extra.{sort_fixture.vendor_key}"
    params = _fil_params(sort_fixture, f"{key}:asc")
    a, b, c = sort_fixture.filament_ids
    assert _group_keys(params) == _ids([b, c, a])  # alpha, alpha, zeta
    assert _group_keys({**params, "sort": f"{key}:desc"}) == _ids([a, b, c])


def test_group_filament_count_sort(sort_fixture: SortFixture):
    v_zeta, v_alpha, _v_none = sort_fixture.vendor_ids
    params = {
        "group_by": "vendor",
        "include_empty": "true",
        "filament.vendor.id": ",".join(str(i) for i in sort_fixture.vendor_ids),
    }
    assert _group_keys({**params, "sort": "group.filament_count:desc"})[:2] == _ids([v_alpha, v_zeta])
    # Valid on the filament axis too (each group holds one filament).
    assert len(_group_keys(_fil_params(sort_fixture, "group.filament_count:asc"))) == 3


def test_extra_field_sort_does_not_change_aggregates(sort_fixture: SortFixture):
    """The extra-field join is at most one row per entity, so sums and counts stay the same."""
    key = f"filament.extra.{sort_fixture.int_key}"
    vkey = f"filament.vendor.extra.{sort_fixture.vendor_key}"

    def aggregates(params: dict[str, str]) -> dict[str, tuple[int, float]]:
        result = httpx.get(f"{URL}/api/v1/spool/group", params=params)
        result.raise_for_status()
        return {g["key"]: (g["spool_count"], g["total_remaining_weight"]) for g in result.json()}

    ids = ",".join(str(i) for i in sort_fixture.filament_ids)
    for include_empty in ("true", "false"):
        base = {"group_by": "filament", "filament.id": ids, "include_empty": include_empty}
        plain = aggregates(base)
        assert plain[str(sort_fixture.filament_ids[0])] == (2, 800)
        assert aggregates({**base, "sort": f"{key}:asc,{vkey}:desc"}) == plain

    vendor_base = {"group_by": "vendor", "filament.vendor.id": ",".join(str(i) for i in sort_fixture.vendor_ids)}
    for include_empty in ("true", "false"):
        base = {**vendor_base, "include_empty": include_empty}
        assert aggregates({**base, "sort": f"{key}:asc,{vkey}:desc"}) == aggregates(base)


def test_unknown_extra_key_is_ignored(sort_fixture: SortFixture):
    keys = _group_keys(_fil_params(sort_fixture, "filament.extra.nope:asc,group.title:asc"))
    assert len(keys) == 3


@pytest.mark.parametrize("sort", ["location:asc", "foo:asc", "filament.nope:asc", "filament.vendor.nope:desc"])
def test_sort_by_unknown_path_is_ignored(sort_fixture: SortFixture, sort: str):
    """A sort key that doesn't resolve is ignored, as it always was: rejecting it now would break callers."""
    keys = _group_keys(_fil_params(sort_fixture, f"{sort},group.title:asc"))
    assert keys == _group_keys(_fil_params(sort_fixture, "group.title:asc"))


def test_sort_composes_vendor_name_then_field(sort_fixture: SortFixture):
    a, b, c = sort_fixture.filament_ids  # vendors B-, A-, A-
    sort = "group.vendor_name:asc,filament.settings_extruder_temp:desc,group.title:asc"
    assert _group_keys(_fil_params(sort_fixture, sort)) == _ids([b, c, a])
