"""Unit tests for natural-language search validation (#362, B2).

The DB-backed grounding is exercised in the integration suite; here we pin the pure
validators that decide what survives into a filter — the hallucination guard, the colour
and sort checks — with no model or database involved.
"""
# ruff: noqa: SLF001 -- this module deliberately unit-tests nlsearch's internal validators.

from spoolman import nlsearch

_VOCAB = {
    "materials": ["PLA", "PETG", "ASA"],
    "vendors": ["Prusament", "Polymaker"],
    "locations": ["Shelf B", "Dry Box 1"],
    "lot_numbers": ["A123"],
}


def test_ground_keeps_only_known_values_in_db_casing() -> None:
    # Case-insensitive match, canonical casing returned; unknown value dropped.
    assert nlsearch._ground(["petg", "Unobtanium"], _VOCAB["materials"]) == ["PETG"]


def test_ground_dedups() -> None:
    assert nlsearch._ground(["PLA", "pla"], _VOCAB["materials"]) == ["PLA"]


def test_validate_builds_grounded_filters_and_drops_hallucinations() -> None:
    raw = {
        "material": ["PETG", "Kryptonite"],
        "vendor": ["Prusament"],
        "location": ["shelf b"],
        "lot_nr": ["nope"],
        "color_hex": "#00FF00",
        "search": "  matte  ",
        "sort": {"field": "remaining_weight", "direction": "asc"},
    }
    result = nlsearch._validate(raw, _VOCAB)
    fields = {f["field"]: f["values"] for f in result["filters"]}
    assert fields["filament.material"] == ["PETG"]
    assert fields["filament.vendor.name"] == ["Prusament"]
    assert fields["location"] == ["Shelf B"]
    assert "lot_nr" not in fields  # 'nope' is not a real lot number
    assert result["color_hex"] == "00ff00"  # normalised: '#' stripped, lower-cased
    assert result["search"] == "matte"
    assert result["sort"] == {"field": "remaining_weight", "direction": "asc"}


def test_valid_color_hex_rejects_junk() -> None:
    assert nlsearch._valid_color_hex("abcdef") == "abcdef"
    assert nlsearch._valid_color_hex("#ABCDEF") == "abcdef"
    assert nlsearch._valid_color_hex("red") is None
    assert nlsearch._valid_color_hex("12345") is None  # too short
    assert nlsearch._valid_color_hex(None) is None


def test_valid_sort_rejects_unknown_field_and_direction() -> None:
    assert nlsearch._valid_sort({"field": "remaining_weight", "direction": "desc"}) == {
        "field": "remaining_weight",
        "direction": "desc",
    }
    assert nlsearch._valid_sort({"field": "password", "direction": "asc"}) is None
    assert nlsearch._valid_sort({"field": "price", "direction": "sideways"}) is None
    assert nlsearch._valid_sort("nope") is None


def test_as_list_coerces_string_and_list() -> None:
    assert nlsearch._as_list("PLA") == ["PLA"]
    assert nlsearch._as_list(["PLA", "", "PETG"]) == ["PLA", "PETG"]
    assert nlsearch._as_list(None) == []
    assert nlsearch._as_list(123) == []
