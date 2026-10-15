"""GET /spool/group: vendor groups, manufacturer sorting, previews, totals and catalogue sort keys.

Ported from upstream commits 02f5c07c1 (group.vendor_name sort, include_empty for group_by=vendor,
filament_count on vendor groups, preview=true, X-Total-Spools / X-Total-Remaining-Weight headers)
and 30928407a (filament.<column>, filament.vendor.<column>, filament.extra.<key>,
filament.vendor.extra.<key> and group.filament_count sort keys) from
tests_integration/tests/spool/test_group.py.

Upstream's module-scoped fixtures become per-test seed helpers here, since each test gets a fresh
database. The `registered` date filter in upstream's include_empty rejection test is dropped: this
fork's group endpoint has no date filters.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient, Response

GROUP = "/api/v1/spool/group"
FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"


async def _post(client: AsyncClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    resp = await client.post(f"/api/v1/{path}", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _filament(client: AsyncClient, name: str, vendor_id: int | None, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    payload = {"name": name, "material": "PLA", "density": 1.25, "diameter": 1.75, "weight": 1000, **extra}
    if vendor_id is not None:
        payload["vendor_id"] = vendor_id
    return await _post(client, "filament", payload)


async def _groups(client: AsyncClient, params: dict[str, Any]) -> Response:
    resp = await client.get(GROUP, params=params)
    assert resp.status_code == 200, resp.text
    return resp


def _by_key(groups: list[dict]) -> dict[str, dict]:
    return {g["key"]: g for g in groups}


# --- Vendor groups, manufacturer sorting, previews and totals -----------------------------------


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


async def _seed_vendors(client: AsyncClient) -> VendorFixture:
    """Vendors A < B < C by name, with the filaments and spools described on VendorFixture."""
    tag = uuid.uuid4().hex[:8]
    vendor_ids = [(await _post(client, "vendor", {"name": f"{tag}-{letter}"}))["id"] for letter in "ABC"]
    vendor_a, vendor_b, vendor_c = vendor_ids
    a1 = (await _filament(client, f"{tag}-a1", vendor_a))["id"]
    a2 = (await _filament(client, f"{tag}-a2", vendor_a))["id"]
    b1 = (await _filament(client, f"{tag}-b1", vendor_b))["id"]
    none1 = (await _filament(client, f"{tag}-none", None))["id"]

    a1_spool_ids = [
        (await _post(client, "spool", {"filament_id": a1, "remaining_weight": 500}))["id"] for _ in range(6)
    ]
    a1_archived = (await _post(client, "spool", {"filament_id": a1, "remaining_weight": 1000, "archived": True}))["id"]
    b1_spool = (await _post(client, "spool", {"filament_id": b1, "remaining_weight": 200}))["id"]
    b1_archived = (await _post(client, "spool", {"filament_id": b1, "remaining_weight": 100, "archived": True}))["id"]
    none_spool = (await _post(client, "spool", {"filament_id": none1, "remaining_weight": 200}))["id"]

    return VendorFixture(
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
        spool_ids=[*a1_spool_ids, a1_archived, b1_spool, b1_archived, none_spool],
    )


async def test_group_sort_vendor_name_orders_by_manufacturer_with_vendorless_last(client: AsyncClient):
    """group.vendor_name sections filament groups by manufacturer; no manufacturer goes last, both ways."""
    f = await _seed_vendors(client)
    expected = [f.a1, f.a2, f.b1, f.none1]
    params = {"group_by": "filament", "filament.id": f.filament_ids, "include_empty": "true"}
    result = await _groups(client, {**params, "sort": "group.vendor_name:asc,group.title:asc"})
    assert [int(g["key"]) for g in result.json()] == expected

    # Descending flips the manufacturers but the vendorless filament still sinks to the bottom.
    result = await _groups(client, {**params, "sort": "group.vendor_name:desc,group.title:asc"})
    assert [int(g["key"]) for g in result.json()] == [f.b1, f.a1, f.a2, f.none1]

    # Paging with the boundary between the two vendors in the middle of the page break.
    sort = "group.vendor_name:asc,group.title:asc"
    first = await _groups(client, {**params, "sort": sort, "limit": 2, "offset": 0})
    second = await _groups(client, {**params, "sort": sort, "limit": 2, "offset": 2})
    assert first.headers["x-total-count"] == "4"
    assert [int(g["key"]) for g in first.json()] == expected[:2]
    assert [int(g["key"]) for g in second.json()] == expected[2:]


async def test_group_by_vendor_sorted_by_vendor_name(client: AsyncClient):
    """The sort key is valid on the vendor axis itself too."""
    f = await _seed_vendors(client)
    result = await _groups(
        client,
        {
            "group_by": "vendor",
            "filament.vendor.id": f.vendor_ids,
            "include_empty": "true",
            "sort": "group.vendor_name:desc",
        },
    )
    assert [int(g["key"]) for g in result.json()] == [f.vendor_c, f.vendor_b, f.vendor_a]


async def test_group_by_vendor_include_empty(client: AsyncClient):
    """A manufacturer with no filaments is a group of zeros; filament_count counts all its filaments."""
    f = await _seed_vendors(client)
    params = {"group_by": "vendor", "filament.vendor.id": f.vendor_ids}

    plain = _by_key((await _groups(client, params)).json())
    assert plain.keys() == {str(f.vendor_a), str(f.vendor_b)}
    # Spool-driven: only the filaments that have a matching spool count.
    assert plain[str(f.vendor_a)]["filament_count"] == 1
    assert plain[str(f.vendor_b)]["filament_count"] == 1

    result = await _groups(client, {**params, "include_empty": "true"})
    assert result.headers["x-total-count"] == "3"
    groups = _by_key(result.json())
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
    result = await _groups(client, {**params, "include_empty": "true", "allow_archived": "true"})
    groups = _by_key(result.json())
    assert groups[str(f.vendor_a)]["spool_count"] == 7
    assert groups[str(f.vendor_c)]["spool_count"] == 0

    # A filament-level filter applies as a WHERE: only manufacturers with a matching filament remain.
    result = await _groups(client, {**params, "include_empty": "true", "filament.id": str(f.a2)})
    groups = _by_key(result.json())
    assert groups.keys() == {str(f.vendor_a)}
    assert groups[str(f.vendor_a)]["filament_count"] == 1
    assert groups[str(f.vendor_a)]["spool_count"] == 0

    # The vendor-less filament's group is not listed: this mode lists manufacturers.
    result = await _groups(client, {"group_by": "vendor", "include_empty": "true", "filament.id": str(f.none1)})
    assert result.json() == []


async def test_group_by_vendor_include_empty_rejections(client: AsyncClient):
    """Spool-scoped filters stay a 400 for vendors, and other axes still are.

    Upstream also tries a `registered` date filter; this fork has none.
    """
    for params in ({"location": '"Shelf A"'}, {"lot_nr": '"B12"'}):
        resp = await client.get(GROUP, params={"group_by": "vendor", "include_empty": "true", **params})
        assert resp.status_code == 400, params
    for group_by in ("material", "location"):
        resp = await client.get(GROUP, params={"group_by": group_by, "include_empty": "true"})
        assert resp.status_code == 400, group_by


async def test_group_by_filament_has_no_filament_count(client: AsyncClient):
    """filament_count belongs to vendor groups only."""
    f = await _seed_vendors(client)
    result = await _groups(client, {"group_by": "filament", "filament.id": str(f.a1)})
    assert "filament_count" not in result.json()[0]


async def test_group_preview_spools_for_filament_groups(client: AsyncClient):
    """A filament group previews up to 5 of exactly the spools its spool_count counted, by id."""
    f = await _seed_vendors(client)
    params = {"group_by": "filament", "filament.id": f"{f.a1},{f.b1},{f.a2}", "include_empty": "true"}

    assert all("spools" not in g for g in (await _groups(client, params)).json())

    groups = _by_key((await _groups(client, {**params, "preview": "true"})).json())
    a1 = groups[str(f.a1)]
    assert a1["spool_count"] == 6
    assert [s["id"] for s in a1["spools"]] == f.a1_spool_ids[:5]
    assert a1["spools"][0] == {"id": f.a1_spool_ids[0], "remaining_weight": 500, "initial_weight": 1000}
    assert groups[str(f.a2)]["spools"] == []  # an empty group previews as empty, not as absent
    b1 = groups[str(f.b1)]
    assert [s["remaining_weight"] for s in b1["spools"]] == [200]  # archived spool excluded

    groups = _by_key((await _groups(client, {**params, "preview": "true", "allow_archived": "true"})).json())
    b1 = groups[str(f.b1)]
    assert b1["spool_count"] == 2
    assert [s["id"] for s in b1["spools"]][-1] == f.b1_archived_spool_id
    assert len(b1["spools"]) == b1["spool_count"]
    assert len(groups[str(f.a1)]["spools"]) == 5


async def test_group_preview_spools_follow_spool_filters(client: AsyncClient):
    """Spool-level filters reach the preview, so it never shows a spool the group did not count."""
    f = await _seed_vendors(client)
    target = f.a1_spool_ids[2]
    location = f"pv-{uuid.uuid4().hex[:8]}"
    resp = await client.patch(f"{SPOOL}/{target}", json={"location": location})
    assert resp.status_code == 200, resp.text

    result = await _groups(
        client,
        {"group_by": "filament", "filament.id": str(f.a1), "location": f'"{location}"', "preview": "true"},
    )
    group = result.json()[0]
    assert group["spool_count"] == 1
    assert [s["id"] for s in group["spools"]] == [target]


async def test_group_preview_filaments_for_vendor_groups(client: AsyncClient):
    """A vendor group previews up to 4 of its filaments, by name, with their colors."""
    tag = uuid.uuid4().hex[:8]
    vendor_id = (await _post(client, "vendor", {"name": f"{tag}-many"}))["id"]
    filaments = [
        await _filament(
            client,
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
    await _post(client, "spool", {"filament_id": filaments[4]["id"], "remaining_weight": 100})

    params = {"group_by": "vendor", "filament.vendor.id": str(vendor_id)}
    assert "filaments" not in (await _groups(client, params)).json()[0]
    for extra in ({}, {"include_empty": "true"}):
        group = (await _groups(client, {**params, **extra, "preview": "true"})).json()[0]
        assert [x["id"] for x in group["filaments"]] == [x["id"] for x in filaments[:4]]
        assert group["filaments"][0]["multi_color_hexes"] == "FF0000,00FF00"
        assert group["filaments"][0]["multi_color_direction"] == "coaxial"
        assert group["filaments"][1] == {"id": filaments[1]["id"], "color_hex": "0000FF"}
        assert "spools" not in group
    assert (await _groups(client, {**params, "preview": "true"})).json()[0]["filament_count"] == 1
    result = await _groups(client, {**params, "preview": "true", "include_empty": "true"})
    assert result.json()[0]["filament_count"] == 5


async def test_group_preview_ignored_for_other_axes(client: AsyncClient):
    """Material/location groups have no members to preview."""
    f = await _seed_vendors(client)
    for group_by in ("material", "location"):
        result = await _groups(client, {"group_by": group_by, "filament.id": f.filament_ids, "preview": "true"})
        assert result.json()
        assert all("spools" not in g and "filaments" not in g for g in result.json())


async def test_group_total_headers(client: AsyncClient):
    """x-total-spools / x-total-remaining-weight sum every matching group, not just the page."""
    f = await _seed_vendors(client)
    params = {"group_by": "filament", "filament.id": f.filament_ids}
    result = await _groups(client, {**params, "limit": 1})
    assert len(result.json()) == 1
    assert result.headers["x-total-count"] == "3"
    assert result.headers["x-total-spools"] == "8"  # 6 + 1 + 1, archived excluded
    assert float(result.headers["x-total-remaining-weight"]) == pytest.approx(3400)

    result = await _groups(client, {**params, "include_empty": "true", "limit": 1})
    assert result.headers["x-total-count"] == "4"
    assert result.headers["x-total-spools"] == "8"  # empty groups add groups, not spools
    assert float(result.headers["x-total-remaining-weight"]) == pytest.approx(3400)

    result = await _groups(client, {**params, "allow_archived": "true"})
    assert result.headers["x-total-spools"] == "10"
    assert float(result.headers["x-total-remaining-weight"]) == pytest.approx(4500)

    # No matching groups at all: zeros, not a missing header or "None".
    result = await _groups(client, {"group_by": "filament", "filament.id": "999999999"})
    assert result.headers["x-total-count"] == "0"
    assert result.headers["x-total-spools"] == "0"
    assert float(result.headers["x-total-remaining-weight"]) == 0


# --- Sorting groups by filament / manufacturer columns and extra fields -------------------------


@dataclass
class SortFixture:
    vendor_ids: list[int]  # empty_spool_weight 300, 100, unset (no filaments)
    filament_ids: list[int]  # temps 210, 190, unset; "n" extra 10, 9, unset
    int_key: str
    vendor_key: str


async def _seed_sort(client: AsyncClient) -> SortFixture:
    """Three vendors (the last without filaments) and three filaments, each with a NULL somewhere."""
    suffix = uuid.uuid4().hex[:8]
    int_key = f"n_{suffix}"
    vendor_key = f"v_{suffix}"
    await _post(client, f"field/filament/{int_key}", {"name": "N", "field_type": "integer"})
    await _post(client, f"field/vendor/{vendor_key}", {"name": "V", "field_type": "text"})

    vendor_ids: list[int] = []
    for name, weight, extra in (("B", 300, "zeta"), ("A", 100, "alpha"), ("C", None, None)):
        payload: dict[str, Any] = {"name": f"{name}-{suffix}"}
        if weight is not None:
            payload["empty_spool_weight"] = weight
        if extra is not None:
            payload["extra"] = {vendor_key: json.dumps(extra)}
        vendor_ids.append((await _post(client, "vendor", payload))["id"])

    filament_ids = [
        (
            await _filament(
                client,
                f"Sort-{uuid.uuid4().hex[:8]}",
                vendor_ids[0],
                settings_extruder_temp=210,
                extra={int_key: json.dumps(10)},
            )
        )["id"],
        (
            await _filament(
                client,
                f"Sort-{uuid.uuid4().hex[:8]}",
                vendor_ids[1],
                settings_extruder_temp=190,
                extra={int_key: json.dumps(9)},
            )
        )["id"],
        (await _filament(client, f"Sort-{uuid.uuid4().hex[:8]}", vendor_ids[1]))["id"],
    ]
    for filament_id, weights in zip(filament_ids, ([500, 300], [100], []), strict=True):
        for weight in weights:
            await _post(client, "spool", {"filament_id": filament_id, "remaining_weight": weight})

    return SortFixture(vendor_ids=vendor_ids, filament_ids=filament_ids, int_key=int_key, vendor_key=vendor_key)


async def _group_keys(client: AsyncClient, params: dict[str, str]) -> list[str]:
    return [group["key"] for group in (await _groups(client, params)).json()]


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


async def test_sort_by_filament_column_nulls_last(client: AsyncClient):
    fx = await _seed_sort(client)
    a, b, c = fx.filament_ids
    asc = await _group_keys(client, _fil_params(fx, "filament.settings_extruder_temp:asc"))
    desc = await _group_keys(client, _fil_params(fx, "filament.settings_extruder_temp:desc"))
    assert asc == _ids([b, a, c])
    assert desc == _ids([a, b, c])


async def test_sort_by_vendor_column_for_vendor_groups(client: AsyncClient):
    fx = await _seed_sort(client)
    v300, v100, _v_none = fx.vendor_ids
    params = {
        "group_by": "vendor",
        "include_empty": "true",
        "filament.vendor.id": ",".join(str(i) for i in fx.vendor_ids),
    }
    asc = await _group_keys(client, {**params, "sort": "filament.vendor.empty_spool_weight:asc"})
    desc = await _group_keys(client, {**params, "sort": "filament.vendor.empty_spool_weight:desc"})
    assert asc[:2] == _ids([v100, v300])
    assert desc[:2] == _ids([v300, v100])


async def test_sort_by_vendor_column_includes_filamentless_vendor_last(client: AsyncClient):
    fx = await _seed_sort(client)
    v300, v100, v_none = fx.vendor_ids
    result = await _groups(
        client,
        {"group_by": "vendor", "include_empty": "true", "sort": "filament.vendor.empty_spool_weight:asc"},
    )
    keys = [g["key"] for g in result.json() if g["key"] in _ids(fx.vendor_ids)]
    assert keys == _ids([v100, v300, v_none])


async def test_sort_by_integer_extra_field_is_numeric(client: AsyncClient):
    fx = await _seed_sort(client)
    a, b, c = fx.filament_ids  # 10, 9, unset
    key = f"filament.extra.{fx.int_key}"
    assert await _group_keys(client, _fil_params(fx, f"{key}:asc")) == _ids([b, a, c])
    assert await _group_keys(client, _fil_params(fx, f"{key}:desc")) == _ids([a, b, c])


async def test_sort_by_vendor_extra_field(client: AsyncClient):
    fx = await _seed_sort(client)
    key = f"filament.vendor.extra.{fx.vendor_key}"
    params = _fil_params(fx, f"{key}:asc")
    a, b, c = fx.filament_ids
    assert await _group_keys(client, params) == _ids([b, c, a])  # alpha, alpha, zeta
    assert await _group_keys(client, {**params, "sort": f"{key}:desc"}) == _ids([a, b, c])


async def test_group_filament_count_sort(client: AsyncClient):
    fx = await _seed_sort(client)
    v_zeta, v_alpha, _v_none = fx.vendor_ids
    params = {
        "group_by": "vendor",
        "include_empty": "true",
        "filament.vendor.id": ",".join(str(i) for i in fx.vendor_ids),
    }
    assert (await _group_keys(client, {**params, "sort": "group.filament_count:desc"}))[:2] == _ids([v_alpha, v_zeta])
    # Valid on the filament axis too (each group holds one filament).
    assert len(await _group_keys(client, _fil_params(fx, "group.filament_count:asc"))) == 3


async def test_extra_field_sort_does_not_change_aggregates(client: AsyncClient):
    """The extra-field join is at most one row per entity, so sums and counts stay the same."""
    fx = await _seed_sort(client)
    key = f"filament.extra.{fx.int_key}"
    vkey = f"filament.vendor.extra.{fx.vendor_key}"

    async def aggregates(params: dict[str, str]) -> dict[str, tuple[int, float]]:
        result = await _groups(client, params)
        return {g["key"]: (g["spool_count"], g["total_remaining_weight"]) for g in result.json()}

    ids = ",".join(str(i) for i in fx.filament_ids)
    for include_empty in ("true", "false"):
        base = {"group_by": "filament", "filament.id": ids, "include_empty": include_empty}
        plain = await aggregates(base)
        assert plain[str(fx.filament_ids[0])] == (2, 800)
        assert await aggregates({**base, "sort": f"{key}:asc,{vkey}:desc"}) == plain

    vendor_base = {"group_by": "vendor", "filament.vendor.id": ",".join(str(i) for i in fx.vendor_ids)}
    for include_empty in ("true", "false"):
        base = {**vendor_base, "include_empty": include_empty}
        assert await aggregates({**base, "sort": f"{key}:asc,{vkey}:desc"}) == await aggregates(base)


async def test_unknown_extra_key_is_ignored(client: AsyncClient):
    fx = await _seed_sort(client)
    keys = await _group_keys(client, _fil_params(fx, "filament.extra.nope:asc,group.title:asc"))
    assert len(keys) == 3


@pytest.mark.parametrize(
    "sort",
    [
        "location:asc",
        "foo:asc",
        "filament.nope:asc",
        "filament.vendor.nope:desc",
        "filament.extra:asc",
        "filament.vendor:asc",
    ],
)
async def test_sort_by_unknown_path_is_ignored(client: AsyncClient, sort: str):
    """A sort key that doesn't resolve is ignored, as it always was: rejecting it now would break callers."""
    fx = await _seed_sort(client)
    keys = await _group_keys(client, _fil_params(fx, f"{sort},group.title:asc"))
    assert keys == await _group_keys(client, _fil_params(fx, "group.title:asc"))


async def test_sort_composes_vendor_name_then_field(client: AsyncClient):
    fx = await _seed_sort(client)
    a, b, c = fx.filament_ids  # vendors B-, A-, A-
    sort = "group.vendor_name:asc,filament.settings_extruder_temp:desc,group.title:asc"
    assert await _group_keys(client, _fil_params(fx, sort)) == _ids([b, c, a])
