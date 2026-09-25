"""Integration tests for GET /spool/group?include_empty=true on every supported database (#444).

Ported from upstream's tests_integration/tests/spool/test_group.py (33ad8d71, 6dce8717), minus
the first_used/last_used/registered filters this fork's group endpoint does not have. The query
selects FROM the filaments and outer-joins the spools, which is where the four databases differ.
"""

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from ..conftest import URL

# --- include_empty: filaments with no spools -------------------------------
#
# Grouping aggregates over spools, so a filament nobody owns a spool of can never
# produce a group and simply vanishes from the list -- which reads as "in stock"
# when it means the opposite (#1092). include_empty turns the query around and
# lists it as a group of zero.


@dataclass
class EmptyFixture:
    stocked_id: int
    empty_id: int
    archived_only_id: int
    spool_ids: list[int]


@pytest.fixture(scope="module")
def empty_group_filaments(random_vendor_mod: dict[str, Any]) -> Iterable[EmptyFixture]:
    """Three filaments of one vendor: one stocked, one with only an archived spool, one with none."""
    filament_ids: list[int] = []
    for name, material in (("Stocked", "PLA"), ("Empty", "ABS"), ("ArchivedOnly", "PETG")):
        result = httpx.post(
            f"{URL}/api/v1/filament",
            json={
                "name": f"{name}-{uuid.uuid4().hex[:8]}",
                "vendor_id": random_vendor_mod["id"],
                "material": material,
                "density": 1.25,
                "diameter": 1.75,
                "weight": 1000,
            },
        )
        result.raise_for_status()
        filament_ids.append(result.json()["id"])
    stocked_id, empty_id, archived_only_id = filament_ids

    spool_ids: list[int] = []
    for payload in (
        {"filament_id": stocked_id, "remaining_weight": 1000, "location": "Shelf A"},
        {"filament_id": stocked_id, "remaining_weight": 400, "location": "Shelf B"},
        {"filament_id": archived_only_id, "remaining_weight": 900, "archived": True},
    ):
        result = httpx.post(f"{URL}/api/v1/spool", json=payload)
        result.raise_for_status()
        spool_ids.append(result.json()["id"])

    yield EmptyFixture(
        stocked_id=stocked_id,
        empty_id=empty_id,
        archived_only_id=archived_only_id,
        spool_ids=spool_ids,
    )

    for spool_id in spool_ids:
        httpx.delete(f"{URL}/api/v1/spool/{spool_id}").raise_for_status()
    for filament_id in filament_ids:
        httpx.delete(f"{URL}/api/v1/filament/{filament_id}").raise_for_status()


def _group_by_key(groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {group["key"]: group for group in groups}


def _all_ids(fixture: EmptyFixture) -> str:
    return f"{fixture.stocked_id},{fixture.empty_id},{fixture.archived_only_id}"


def test_group_by_filament_omits_empty_by_default(empty_group_filaments: EmptyFixture):
    """Without the flag, only filaments that hold a matching spool are groups."""
    result = httpx.get(
        f"{URL}/api/v1/spool/group",
        params={"group_by": "filament", "filament.id": _all_ids(empty_group_filaments)},
    )
    result.raise_for_status()
    assert result.headers["x-total-count"] == "1"
    assert _group_by_key(result.json()).keys() == {str(empty_group_filaments.stocked_id)}


def test_group_by_filament_include_empty(empty_group_filaments: EmptyFixture):
    """include_empty lists the spool-less filaments too, as groups of zero."""
    result = httpx.get(
        f"{URL}/api/v1/spool/group",
        params={
            "group_by": "filament",
            "filament.id": _all_ids(empty_group_filaments),
            "include_empty": "true",
        },
    )
    result.raise_for_status()
    assert result.headers["x-total-count"] == "3"

    groups = _group_by_key(result.json())
    stocked = groups[str(empty_group_filaments.stocked_id)]
    assert stocked["spool_count"] == 2
    assert stocked["total_remaining_weight"] == pytest.approx(1400)

    for filament_id in (empty_group_filaments.empty_id, empty_group_filaments.archived_only_id):
        group = groups[str(filament_id)]
        assert group["group_by"] == "filament"
        assert group["spool_count"] == 0
        assert group["in_use_count"] == 0
        assert group["total_remaining_weight"] == pytest.approx(0)
        # The filament is hydrated exactly as a populated group's is, so the client can
        # draw the same header (name, colour, manufacturer) for it.
        assert group["filament"]["id"] == filament_id
        # Never used, so no timestamp -- excluded from the response rather than zeroed.
        assert "last_used" not in group


def test_include_empty_respects_allow_archived(empty_group_filaments: EmptyFixture):
    """A filament is only empty relative to the spools being counted."""
    result = httpx.get(
        f"{URL}/api/v1/spool/group",
        params={
            "group_by": "filament",
            "filament.id": _all_ids(empty_group_filaments),
            "include_empty": "true",
            "allow_archived": "true",
        },
    )
    result.raise_for_status()
    groups = _group_by_key(result.json())
    assert groups[str(empty_group_filaments.archived_only_id)]["spool_count"] == 1
    assert groups[str(empty_group_filaments.empty_id)]["spool_count"] == 0


def test_include_empty_applies_filament_filters(empty_group_filaments: EmptyFixture):
    """Filament-level filters select which filaments are groups, empty ones included."""
    result = httpx.get(
        f"{URL}/api/v1/spool/group",
        params={
            "group_by": "filament",
            "filament.id": _all_ids(empty_group_filaments),
            "filament.material": '"ABS"',
            "include_empty": "true",
        },
    )
    result.raise_for_status()
    assert result.headers["x-total-count"] == "1"
    groups = result.json()
    assert groups[0]["key"] == str(empty_group_filaments.empty_id)
    assert groups[0]["spool_count"] == 0


def test_include_empty_sorts_and_pages_over_all_groups(empty_group_filaments: EmptyFixture):
    """Empty groups take part in ordering and pagination like any other group."""
    params = {
        "group_by": "filament",
        "filament.id": _all_ids(empty_group_filaments),
        "include_empty": "true",
        "sort": "group.spool_count:desc",
    }
    result = httpx.get(f"{URL}/api/v1/spool/group", params=params)
    result.raise_for_status()
    assert [g["spool_count"] for g in result.json()] == [2, 0, 0]

    # Paging over the same ordering must partition the groups, never repeat or drop one.
    seen: list[str] = []
    for offset in (0, 2):
        page = httpx.get(f"{URL}/api/v1/spool/group", params={**params, "limit": 2, "offset": offset})
        page.raise_for_status()
        assert page.headers["x-total-count"] == "3"
        seen.extend(g["key"] for g in page.json())
    assert sorted(seen) == sorted(
        [
            str(empty_group_filaments.stocked_id),
            str(empty_group_filaments.empty_id),
            str(empty_group_filaments.archived_only_id),
        ],
    )


def test_include_empty_applies_filament_extra_field_filters():
    """A filament extra field selects empty groups too, which is a different join from the spool query.

    The spool query reaches a filament's extra fields through Spool.filament_id; this one has no
    spool to go through and matches on Filament.id directly (see apply_spool_related_extra_filters'
    link_column). A filament with no spools has to answer the filter on its own.
    """
    grade_key = f"grade_{uuid.uuid4().hex[:8]}"
    httpx.post(
        f"{URL}/api/v1/field/filament/{grade_key}",
        json={"name": "Grade", "field_type": "text"},
    ).raise_for_status()

    filament_ids: list[int] = []
    try:
        for grade in ("Premium", "Standard"):
            result = httpx.post(
                f"{URL}/api/v1/filament",
                json={
                    "name": f"Grade-{grade}-{uuid.uuid4().hex[:8]}",
                    "density": 1.25,
                    "diameter": 1.75,
                    "extra": {grade_key: json.dumps(grade)},
                },
            )
            result.raise_for_status()
            filament_ids.append(result.json()["id"])
        premium_id, _standard_id = filament_ids

        # Neither filament has a single spool, so without include_empty there is nothing at all.
        result = httpx.get(
            f"{URL}/api/v1/spool/group",
            params={"group_by": "filament", f"filament.extra.{grade_key}": '"Premium"'},
        )
        result.raise_for_status()
        assert result.json() == []

        result = httpx.get(
            f"{URL}/api/v1/spool/group",
            params={
                "group_by": "filament",
                f"filament.extra.{grade_key}": '"Premium"',
                "include_empty": "true",
            },
        )
        result.raise_for_status()
        assert result.headers["x-total-count"] == "1"
        group = result.json()[0]
        assert group["key"] == str(premium_id)
        assert group["spool_count"] == 0
    finally:
        for filament_id in filament_ids:
            httpx.delete(f"{URL}/api/v1/filament/{filament_id}").raise_for_status()
        httpx.delete(f"{URL}/api/v1/field/filament/{grade_key}").raise_for_status()


def test_include_empty_rejected_for_other_group_by():
    """Every other axis is keyed by a value read off the spools, so it has no empty groups."""
    for group_by in ("vendor", "material", "location"):
        result = httpx.get(
            f"{URL}/api/v1/spool/group",
            params={"group_by": group_by, "include_empty": "true"},
        )
        assert result.status_code == 400, group_by


def test_include_empty_rejected_with_spool_level_filters(empty_group_filaments: EmptyFixture):
    """Asking for filaments with no spools AND filtering on the spools is a contradiction.

    Answering it either way is worse than refusing: the filter would delete every empty group,
    silently making the flag a no-op, or be dropped, returning the whole catalogue as empty.
    """
    for params in (
        {"location": '"Shelf A"'},
        {"lot_nr": '"B12"'},
    ):
        result = httpx.get(
            f"{URL}/api/v1/spool/group",
            params={"group_by": "filament", "include_empty": "true", **params},
        )
        assert result.status_code == 400, params

    # A spool extra field is spool-level too, whatever it is called.
    field_key = f"opened_{uuid.uuid4().hex[:8]}"
    httpx.post(
        f"{URL}/api/v1/field/spool/{field_key}",
        json={"name": "Opened", "field_type": "text"},
    ).raise_for_status()
    try:
        result = httpx.get(
            f"{URL}/api/v1/spool/group",
            params={"group_by": "filament", "include_empty": "true", f"extra.{field_key}": '"yes"'},
        )
        assert result.status_code == 400
    finally:
        httpx.delete(f"{URL}/api/v1/field/spool/{field_key}").raise_for_status()

    # Archiving is the exception: it is the default view, and a filament whose every spool is
    # archived genuinely has none to print with, so it belongs in the list as an empty group.
    result = httpx.get(
        f"{URL}/api/v1/spool/group",
        params={
            "group_by": "filament",
            "include_empty": "true",
            "filament.id": _all_ids(empty_group_filaments),
        },
    )
    result.raise_for_status()
    assert _group_by_key(result.json())[str(empty_group_filaments.archived_only_id)]["spool_count"] == 0
