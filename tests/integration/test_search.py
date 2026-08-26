"""Integration tests for the cross-entity `GET /search` endpoint.

Ported from upstream's tests_integration/tests/search/test_search.py to the fork's in-process
ASGI harness (upstream's version drives a real Docker deployment through module-level httpx
calls against a shared, persistent database with a random-suffixed fixture; here each test gets
its own throwaway SQLite database via the `client` fixture, so no unique-suffix dance is needed).
"""

import json
from typing import Any

import pytest
from httpx import AsyncClient

FIELD = "/api/v1/field"
VENDOR = "/api/v1/vendor"
FIL = "/api/v1/filament"
SPOOL = "/api/v1/spool"
SEARCH = "/api/v1/search"

VENDOR_NAME = "SearchVendor"
FILAMENT_NAME = "SearchFilament"
FILAMENT_COMMENT = "fcomment"
SPOOL_LOCATION = "SearchLoc"
SPOOL_COMMENT = "scomment"
TEXT_VALUE = "TextVal"
CHOICE_VALUE = "ChoiceVal"


async def _search(
    client: AsyncClient,
    query: str,
    color_similarity_threshold: float | None = None,
    *,
    allow_archived: bool | None = None,
    spools_per_filament: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"q": query}
    if color_similarity_threshold is not None:
        params["color_similarity_threshold"] = color_similarity_threshold
    if allow_archived is not None:
        params["allow_archived"] = allow_archived
    if spools_per_filament is not None:
        params["spools_per_filament"] = spools_per_filament
    resp = await client.get(SEARCH, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _has(items: list[dict[str, Any]], entity_key: str, entity_id: int, match_field: str) -> bool:
    return any(i[entity_key]["id"] == entity_id and i["match_field"] == match_field for i in items)


def _filament_hit(body: dict[str, Any], filament_id: int) -> dict[str, Any]:
    return next(i for i in body["filaments"] if i["filament"]["id"] == filament_id)


@pytest.fixture
async def data(client: AsyncClient) -> dict[str, Any]:
    """Seed one vendor + one red filament + one spool with text/choice extra fields."""
    resp = await client.post(
        f"{FIELD}/spool/searchtext",
        json={"name": "Search Text", "field_type": "text"},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"{FIELD}/spool/searchchoice",
        json={
            "name": "Search Choice",
            "field_type": "choice",
            "choices": [CHOICE_VALUE, "other"],
            "multi_choice": False,
        },
    )
    assert resp.status_code == 200, resp.text

    vendor = (await client.post(VENDOR, json={"name": VENDOR_NAME})).json()

    filament = (
        await client.post(
            FIL,
            json={
                "name": FILAMENT_NAME,
                "vendor_id": vendor["id"],
                "material": "PLA",
                "density": 1.25,
                "diameter": 1.75,
                "weight": 1000,
                "color_hex": "ff0000",
                "comment": FILAMENT_COMMENT,
            },
        )
    ).json()

    spool = (
        await client.post(
            SPOOL,
            json={
                "filament_id": filament["id"],
                "remaining_weight": 1000,
                "location": SPOOL_LOCATION,
                "comment": SPOOL_COMMENT,
                "extra": {
                    "searchtext": json.dumps(TEXT_VALUE),
                    "searchchoice": json.dumps(CHOICE_VALUE),
                },
            },
        )
    ).json()

    return {"vendor": vendor, "filament": filament, "spool": spool}


async def test_search_filament_name(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, FILAMENT_NAME)
    assert body["is_color_query"] is False
    assert _has(body["filaments"], "filament", data["filament"]["id"], "name")


async def test_search_vendor_name(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, VENDOR_NAME)
    assert _has(body["vendors"], "vendor", data["vendor"]["id"], "name")


async def test_search_filament_comment(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, FILAMENT_COMMENT)
    assert _has(body["filaments"], "filament", data["filament"]["id"], "comment")


async def test_search_spool_location(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, SPOOL_LOCATION)
    assert _has(body["spools"], "spool", data["spool"]["id"], "location")


async def test_search_spool_comment(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, SPOOL_COMMENT)
    assert _has(body["spools"], "spool", data["spool"]["id"], "comment")


async def test_search_extra_text_field(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, TEXT_VALUE)
    assert _has(body["spools"], "spool", data["spool"]["id"], "extra.searchtext")


async def test_search_extra_choice_field(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, CHOICE_VALUE)
    assert _has(body["spools"], "spool", data["spool"]["id"], "extra.searchchoice")


async def test_search_spool_by_id(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, str(data["spool"]["id"]))
    assert _has(body["spools"], "spool", data["spool"]["id"], "id")


async def test_search_color_name(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, "red", color_similarity_threshold=20.0)
    assert body["is_color_query"] is True
    assert _has(body["filaments"], "filament", data["filament"]["id"], "color")


async def test_search_color_hex(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, "#ff0000", color_similarity_threshold=5.0)
    assert body["is_color_query"] is True
    assert _has(body["filaments"], "filament", data["filament"]["id"], "color")


async def test_search_vendor_and_material(client: AsyncClient, data: dict[str, Any]):
    """Terms may match different fields: one the vendor name, one the material."""
    body = await _search(client, f"{VENDOR_NAME} PLA")
    assert _has(body["filaments"], "filament", data["filament"]["id"], "material")


async def test_search_terms_match_different_spool_fields(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, f"{SPOOL_LOCATION} {SPOOL_COMMENT}")
    assert any(i["spool"]["id"] == data["spool"]["id"] for i in body["spools"])


async def test_search_term_matching_native_and_extra_field(client: AsyncClient, data: dict[str, Any]):
    body = await _search(client, f"{SPOOL_LOCATION} {TEXT_VALUE}")
    assert any(i["spool"]["id"] == data["spool"]["id"] for i in body["spools"])


async def test_search_all_terms_required(client: AsyncClient, data: dict[str, Any]):
    """A term that matches nothing excludes the entity, even if the other terms match."""
    assert data["vendor"]["id"]  # ensure the fixture data exists so the empty result is meaningful
    body = await _search(client, f"{VENDOR_NAME} zzznomatch")
    assert body["spools"] == []
    assert body["filaments"] == []
    assert body["vendors"] == []


async def test_search_no_match(client: AsyncClient, data: dict[str, Any]):
    assert data["spool"]["id"]  # ensure the fixture data exists so "no match" is meaningful
    body = await _search(client, "zzznomatch")
    assert body["is_color_query"] is False
    assert body["spools"] == []
    assert body["filaments"] == []
    assert body["vendors"] == []


@pytest.fixture
async def archived_spool(client: AsyncClient, data: dict[str, Any]) -> dict[str, Any]:
    """Create an archived spool sharing the fixture's searchable location."""
    resp = await client.post(
        SPOOL,
        json={
            "filament_id": data["filament"]["id"],
            "remaining_weight": 1000,
            "location": SPOOL_LOCATION,
            "archived": True,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_search_excludes_archived_spools_by_default(client: AsyncClient, archived_spool: dict[str, Any]):
    """Archived spools are hidden unless asked for, matching GET /spool."""
    body = await _search(client, SPOOL_LOCATION)
    assert not _has(body["spools"], "spool", archived_spool["id"], "location")


async def test_search_includes_archived_spools_when_allowed(client: AsyncClient, archived_spool: dict[str, Any]):
    body = await _search(client, SPOOL_LOCATION, allow_archived=True)
    assert _has(body["spools"], "spool", archived_spool["id"], "location")


async def test_search_by_id_respects_allow_archived(client: AsyncClient, archived_spool: dict[str, Any]):
    """The exact-id shortcut must not surface an archived spool either."""
    spool_id = archived_spool["id"]
    assert not _has((await _search(client, str(spool_id)))["spools"], "spool", spool_id, "id")
    assert _has(
        (await _search(client, str(spool_id), allow_archived=True))["spools"],
        "spool",
        spool_id,
        "id",
    )


# --- spools attached to filament results (issue #993) -------------------------------


@pytest.fixture
async def extra_spools(client: AsyncClient, data: dict[str, Any]) -> list[dict[str, Any]]:
    """Two more spools of the fixture's filament, so it has three in total."""
    spools = []
    for _ in range(2):
        resp = await client.post(SPOOL, json={"filament_id": data["filament"]["id"], "remaining_weight": 600})
        assert resp.status_code == 200, resp.text
        spools.append(resp.json())
    return spools


async def test_filament_spools_omitted_by_default(
    client: AsyncClient,
    data: dict[str, Any],
    extra_spools: list[dict[str, Any]],
):
    """Not asking for spools leaves the response exactly as it was before."""
    assert extra_spools  # the filament does have spools to omit
    hit = _filament_hit(await _search(client, FILAMENT_NAME), data["filament"]["id"])
    assert "spools" not in hit
    assert "spool_count" not in hit


async def test_filament_spools_returned_when_requested(
    client: AsyncClient,
    data: dict[str, Any],
    extra_spools: list[dict[str, Any]],
):
    """A filament hit carries its spools, oldest id first, plus the total count."""
    hit = _filament_hit(
        await _search(client, FILAMENT_NAME, spools_per_filament=5),
        data["filament"]["id"],
    )
    expected = sorted([data["spool"]["id"], *(s["id"] for s in extra_spools)])
    assert [s["id"] for s in hit["spools"]] == expected
    assert hit["spool_count"] == 3


async def test_filament_spools_have_remaining_weight(
    client: AsyncClient,
    data: dict[str, Any],
    extra_spools: list[dict[str, Any]],
):
    """The compact spool derives the same remaining weight the spool endpoint reports."""
    hit = _filament_hit(
        await _search(client, FILAMENT_NAME, spools_per_filament=5),
        data["filament"]["id"],
    )
    by_id = {s["id"]: s for s in hit["spools"]}
    assert by_id[data["spool"]["id"]]["remaining_weight"] == pytest.approx(1000)
    assert by_id[extra_spools[0]["id"]]["remaining_weight"] == pytest.approx(600)


async def test_filament_spools_location(client: AsyncClient, data: dict[str, Any]):
    hit = _filament_hit(
        await _search(client, FILAMENT_NAME, spools_per_filament=5),
        data["filament"]["id"],
    )
    assert hit["spools"][0]["location"] == SPOOL_LOCATION


async def test_filament_spools_respect_the_requested_count(
    client: AsyncClient,
    data: dict[str, Any],
    extra_spools: list[dict[str, Any]],
):
    """Only the first N come back, but the count still reports every spool."""
    assert extra_spools
    hit = _filament_hit(
        await _search(client, FILAMENT_NAME, spools_per_filament=2),
        data["filament"]["id"],
    )
    assert len(hit["spools"]) == 2
    assert hit["spool_count"] == 3


async def test_filament_spools_zero_means_omitted(client: AsyncClient, data: dict[str, Any]):
    hit = _filament_hit(
        await _search(client, FILAMENT_NAME, spools_per_filament=0),
        data["filament"]["id"],
    )
    assert "spools" not in hit


async def test_filament_spools_exclude_archived_by_default(
    client: AsyncClient,
    data: dict[str, Any],
    archived_spool: dict[str, Any],
):
    """An archived spool must not be offered as a shortcut, nor counted."""
    hit = _filament_hit(
        await _search(client, FILAMENT_NAME, spools_per_filament=10),
        data["filament"]["id"],
    )
    assert archived_spool["id"] not in [s["id"] for s in hit["spools"]]
    assert hit["spool_count"] == 1


async def test_filament_spools_include_archived_when_allowed(
    client: AsyncClient,
    data: dict[str, Any],
    archived_spool: dict[str, Any],
):
    hit = _filament_hit(
        await _search(client, FILAMENT_NAME, allow_archived=True, spools_per_filament=10),
        data["filament"]["id"],
    )
    archived = next(s for s in hit["spools"] if s["id"] == archived_spool["id"])
    assert archived["archived"] is True
    assert hit["spool_count"] == 2
