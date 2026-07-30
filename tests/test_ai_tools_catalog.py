"""Unit tests for the SpoolmanDB catalog lookup tool."""

import pytest

from spoolman import spoolintake
from spoolman.ai_tools import catalog
from spoolman.ai_tools.base import ToolError


def test_lookup_requires_something_to_match_on() -> None:
    with pytest.raises(ToolError, match="vendor"):
        catalog.build_extraction({})


def test_extraction_maps_tool_args_onto_the_scorer_shape() -> None:
    extraction = catalog.build_extraction({"vendor": " Sunlu ", "name": "Meta PLA", "material": "pla"})
    assert extraction == {"vendor": "Sunlu", "name": "Meta PLA", "material": "pla", "weight_g": None}


def test_rank_coerces_a_string_catalog_weight_like_the_sibling_scorer_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # spoolintake.match_catalog (the sibling scorer Scan-to-Spool uses against this same catalog)
    # runs a catalog entry's "weight" through coerce_number before scoring; _rank must match, or a
    # string weight straight from the JSON-synced catalog would reach _weight_closeness's
    # `b <= 0` comparison uncoerced and raise TypeError the moment a caller ever supplies a real
    # weight_g. build_extraction hardcodes weight_g=None today (so this never fires through the
    # registered tool), but _rank is a shared scoring path, not a private implementation detail of
    # today's one caller -- it must not crash if that ever changes.
    catalog_entries = [
        {"id": "x", "manufacturer": "Sunlu", "name": "PLA Meta", "material": "PLA", "weight": "1000"},
    ]
    monkeypatch.setattr(spoolintake, "load_catalog", lambda: catalog_entries)
    extraction = {"vendor": "Sunlu", "name": "PLA Meta", "material": "PLA", "weight_g": 1000.0}

    rows = catalog._rank(extraction, limit=10)  # noqa: SLF001 -- build_extraction always masks weight_g

    assert rows[0]["external_id"] == "x"


def test_limit_description_does_not_oversell_the_true_default() -> None:
    # arg_limit's own default (25) is immediately capped to 10 in _run_catalog_lookup, so the
    # *effective* default a caller who omits 'limit' actually gets is 10, not 25. The model-facing
    # schema text must say that, not repeat the pre-cap number that a caller never really gets.
    description = catalog.READ_TOOLS["catalog_lookup"].parameters["properties"]["limit"]["description"]
    assert "25" not in description
    assert "10" in description


def test_entry_row_exposes_the_fields_create_filament_needs() -> None:
    entry = {
        "id": "sunlu-pla-black",
        "manufacturer": "Sunlu",
        "name": "PLA Meta",
        "material": "PLA",
        "density": 1.24,
        "diameter": 1.75,
        "weight": 1000,
        "extruder_temp": 210,
        "bed_temp": 60,
    }
    row = catalog.entry_row(entry, score=0.82)
    assert row["density"] == 1.24
    assert row["diameter_mm"] == 1.75
    assert row["match_percent"] == 82


# --- End-to-end through the registered tool (not just the pure helpers) ------------
#
# The tests above only pin build_extraction/entry_row; none of them would fail if the
# tool's run function or its scoring loop were wired up wrong (wrong filter, wrong sort,
# limit not capped, ToolError swallowed). These exercise the actual registered tool
# against a fake catalog, standing in for spoolintake.load_catalog().


async def _lookup(args: dict) -> dict:
    """Call the registered catalog_lookup tool exactly as the chat loop and MCP server do."""
    return await catalog.READ_TOOLS["catalog_lookup"].run(None, args)


#: Deliberately NOT in score order (weakest-of-the-three-survivors first, strongest last):
#: if `_rank` ever stopped sorting, "first in the input" and "first by score" would then
#: disagree, and test_run_catalog_lookup_ranks_best_match_first would actually notice.
_CATALOG = [
    {
        "id": "random-abs",
        "manufacturer": "Some Other Vendor",
        "name": "Totally Different Filament",
        "material": "ABS",
        "density": 1.04,
        "diameter": 1.75,
        "weight": 1000,
        "extruder_temp": 240,
        "bed_temp": 100,
    },
    {
        "id": "prusa-pla",
        "manufacturer": "Prusament",
        "name": "PLA",
        "material": "PLA",
        "density": 1.24,
        "diameter": 1.75,
        "weight": 1000,
        "extruder_temp": 215,
        "bed_temp": 60,
    },
    {
        "id": "sunlu-pla-meta",
        "manufacturer": "Sunlu",
        "name": "PLA Meta",
        "material": "PLA",
        "density": 1.24,
        "diameter": 1.75,
        "weight": 1000,
        "extruder_temp": 210,
        "bed_temp": 60,
    },
]


async def test_run_catalog_lookup_filters_out_low_scoring_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spoolintake, "load_catalog", lambda: _CATALOG)

    result = await _lookup({"vendor": "Sunlu", "name": "PLA Meta", "material": "PLA"})

    ids = {row["external_id"] for row in result["matches"]}
    assert "sunlu-pla-meta" in ids
    assert "random-abs" not in ids  # material mismatch tanks the score below MIN_SCORE
    assert result["count"] == len(result["matches"])


async def test_run_catalog_lookup_ranks_best_match_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spoolintake, "load_catalog", lambda: _CATALOG)

    result = await _lookup({"vendor": "Sunlu", "name": "PLA Meta", "material": "PLA"})

    assert result["matches"][0]["external_id"] == "sunlu-pla-meta"
    percents = [row["match_percent"] for row in result["matches"]]
    assert percents == sorted(percents, reverse=True)


async def test_run_catalog_lookup_caps_the_limit_at_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    many_entries = [
        {
            "id": f"sunlu-pla-{i}",
            "manufacturer": "Sunlu",
            "name": "PLA Meta",
            "material": "PLA",
            "density": 1.24,
            "diameter": 1.75,
            "weight": 1000,
        }
        for i in range(25)
    ]
    monkeypatch.setattr(spoolintake, "load_catalog", lambda: many_entries)

    result = await _lookup({"vendor": "Sunlu", "name": "PLA Meta", "material": "PLA", "limit": 1000})

    assert result["count"] == 10
    assert len(result["matches"]) == 10


async def test_run_catalog_lookup_raises_tool_error_with_no_search_terms() -> None:
    with pytest.raises(ToolError, match="vendor"):
        await _lookup({})


async def test_run_catalog_lookup_degrades_to_empty_when_catalog_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # load_catalog() itself degrades to [] when the sync file is absent/unreadable; the
    # tool must pass that straight through as "no matches", never raise.
    monkeypatch.setattr(spoolintake, "load_catalog", list)

    result = await _lookup({"vendor": "Anyone"})

    assert result == {"count": 0, "matches": []}
