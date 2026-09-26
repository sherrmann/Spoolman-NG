"""Unit tests for Scan-to-Spool intake (#361): reply parsing, normalization, matching.

Oracle strategy: the extraction parser is driven through realistic model-reply shapes
(fences, prose, malformed JSON); normalization through the unit traps a label photo
actually produces (kg-as-grams, "1.75 mm" strings, #-prefixed hex); the matcher through
its pure scoring function and an injected catalog — no DB, no network, no LLM anywhere.
"""

import asyncio
import json

import pytest
import respx
from httpx import Response

from spoolman import decision, spoolintake
from spoolman.spoolintake import (
    ExtractionParseError,
    normalize_extraction,
    parse_json_block,
    score_candidate,
)

# --- Reply parsing -----------------------------------------------------------------


def test_parse_plain_json() -> None:
    assert parse_json_block('{"vendor": "Prusament"}') == {"vendor": "Prusament"}


def test_parse_fenced_json_with_prose() -> None:
    reply = 'Here is the extraction:\n```json\n{"vendor": "Sunlu", "material": "PETG"}\n```'
    assert parse_json_block(reply)["vendor"] == "Sunlu"


@pytest.mark.parametrize("reply", ["no json here", '{"vendor": "x"', "[1, 2, 3]"])
def test_parse_rejects_unusable_replies(reply: str) -> None:
    with pytest.raises(ExtractionParseError):
        parse_json_block(reply)


# --- Normalization -----------------------------------------------------------------


def test_normalize_units_and_strings() -> None:
    out = normalize_extraction(
        {
            "vendor": "  Prusament ",
            "name": "Galaxy Black",
            "material": "PLA",
            "weight_g": "1000 g",
            "diameter_mm": "1,75 mm",
            "extruder_temp_c": 215,
            "lot_nr": "",
            "unknown_key": "dropped",
        },
    )
    assert out["vendor"] == "Prusament"
    assert out["weight_g"] == 1000
    assert out["diameter_mm"] == 1.75
    assert out["extruder_temp_c"] == 215
    assert out["lot_nr"] is None
    assert "unknown_key" not in out
    assert set(out.keys()) == set(spoolintake.EXTRACTION_KEYS)


def test_normalize_reads_tiny_weight_as_kilograms() -> None:
    """A model answering '1' for a 1 kg label must not create a 1 g spool."""
    assert normalize_extraction({"weight_g": 1})["weight_g"] == 1000
    assert normalize_extraction({"weight_g": 750})["weight_g"] == 750


def test_normalize_color_hex() -> None:
    assert normalize_extraction({"color_hex": "#2C3232"})["color_hex"] == "2c3232"
    assert normalize_extraction({"color_hex": "black"})["color_hex"] is None


def test_normalize_confidence() -> None:
    assert normalize_extraction({"confidence": "High"})["confidence"] == "high"
    assert normalize_extraction({"confidence": "certain"})["confidence"] is None
    assert normalize_extraction({"weight_g": True})["weight_g"] is None


# --- Scoring -----------------------------------------------------------------------


_EXTRACTION = {"vendor": "Prusament", "name": "Galaxy Black", "material": "PLA", "weight_g": 1000}


def test_exact_candidate_scores_high() -> None:
    score = score_candidate(_EXTRACTION, vendor="Prusament", name="Galaxy Black", material="PLA", weight_g=1000)
    assert score >= 0.9


def test_material_mismatch_is_penalized_hard() -> None:
    """A PETG label must not match a PLA record even with identical names."""
    score = score_candidate(_EXTRACTION, vendor="Prusament", name="Galaxy Black", material="PETG", weight_g=1000)
    assert score < 0.35


def _esun(material: str) -> float:
    extraction = {"vendor": "eSun", "name": "Black", "material": material, "weight_g": 1000}
    return score_candidate(extraction, vendor="eSun", name="Black", material="PLA+", weight_g=1000)


def test_a_dropped_plus_is_a_partial_match_not_a_mismatch() -> None:
    """A PLA+ spool read as "PLA" must still reach the shortlist (it scored 0.24 before)."""
    assert _esun("PLA") >= spoolintake._CATALOG_MIN_SCORE  # noqa: SLF001
    assert _esun("PLA") < _esun("PLA+"), "an exact material still wins"


def test_plus_variant_works_both_ways() -> None:
    extraction = {"vendor": "eSun", "name": "Black", "material": "PLA+", "weight_g": 1000}
    score = score_candidate(extraction, vendor="eSun", name="Black", material="PLA", weight_g=1000)
    assert score >= spoolintake._CATALOG_MIN_SCORE  # noqa: SLF001


@pytest.mark.parametrize("spelling", ["PLA+", "pla+", "PLA Plus", "PLA PLUS", "PLAPlus", "PLA-Plus", " PLA + "])
def test_plus_spellings_are_the_same_material(spelling: str) -> None:
    assert _esun(spelling) == _esun("PLA+")


@pytest.mark.parametrize(
    ("label", "record"),
    [
        ("PC", "PC+ABS"),  # a plus joining two materials is not a "plus" variant
        ("PLA", "PLA+WOOD"),
        ("ABS", "ABS+GF20"),
        ("PLA", "PETG+"),
    ],
)
def test_other_material_differences_stay_hard_mismatches(label: str, record: str) -> None:
    extraction = {"vendor": "eSun", "name": "Black", "material": label, "weight_g": 1000}
    score = score_candidate(extraction, vendor="eSun", name="Black", material=record, weight_g=1000)
    assert score < 0.35


def test_plus_variant_ranks_below_the_exact_material_in_the_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = [
        _catalog_entry("esun-pla", "eSun", "Black", "PLA", 1000),
        _catalog_entry("esun-pla-plus", "eSun", "Black", "PLA+", 1000),
    ]
    monkeypatch.setattr(spoolintake, "load_catalog", lambda: entries)

    plus_label = spoolintake.match_catalog({"vendor": "eSun", "name": "Black", "material": "PLA+", "weight_g": 1000})
    plain_label = spoolintake.match_catalog({"vendor": "eSun", "name": "Black", "material": "PLA", "weight_g": 1000})

    assert [m["external_id"] for m in plus_label] == ["esun-pla-plus", "esun-pla"]
    assert [m["external_id"] for m in plain_label] == ["esun-pla", "esun-pla-plus"]


def _polymaker(label_name: str, record_name: str) -> float:
    extraction = {"vendor": "Polymaker", "name": label_name, "material": "PLA", "weight_g": 1000}
    return score_candidate(extraction, vendor="Polymaker", name=record_name, material="PLA", weight_g=1000)


def test_a_renamed_product_beats_other_lines_of_the_same_maker() -> None:
    """SpoolmanDB renamed PolyTerra; a label with the old name must still find it."""
    renamed = _polymaker("PolyTerra PLA Charcoal Black", "Panchroma™ Matte (Formerly PolyTerra™) Charcoal Black")
    other_line = _polymaker("PolyTerra PLA Charcoal Black", "PolyLite™ PLA Pro Black")
    other_colour = _polymaker("PolyTerra PLA Charcoal Black", "Panchroma™ Matte (Formerly PolyTerra™) Cotton White")

    assert renamed > other_line
    assert renamed > other_colour


def test_trademark_signs_and_the_material_word_do_not_block_a_word_match() -> None:
    reading, record = "PolyTerra PLA Charcoal Black", "Panchroma™ Matte (Formerly PolyTerra™) Charcoal Black"
    assert spoolintake._similarity(reading, record) < 0.85, "a character comparison misses it"  # noqa: SLF001
    assert spoolintake._name_similarity(reading, record, frozenset({"pla"})) >= 0.85  # noqa: SLF001
    assert spoolintake._name_similarity(reading, record, frozenset()) < 0.85, "the material word blocks it"  # noqa: SLF001


def test_fewer_extra_words_score_higher() -> None:
    """Both candidates contain every word of the reading; the one with fewer extra words wins."""
    assert _polymaker("Charcoal Black", "Matte Charcoal Black") > _polymaker(
        "Charcoal Black",
        "Panchroma™ Matte (Formerly PolyTerra™) Charcoal Black",
    )


def test_equal_word_overlaps_are_ordered_by_character_similarity() -> None:
    """For a reading of "PLA Black", "PLA - Black" must beat every maker's plain "Black"."""
    reading = {"vendor": None, "name": "PLA Black", "material": "PLA", "weight_g": None}
    with_material = score_candidate(reading, vendor="FlashForge", name="PLA - Black", material="PLA", weight_g=1000)
    plain = score_candidate(reading, vendor="3DJAKE", name="Black", material="PLA", weight_g=1000)
    assert with_material > plain


def test_an_exact_name_beats_a_word_match_once_the_material_is_set_aside() -> None:
    """An exact "PLA - White" must beat a plain "White", though both have the same words without "PLA"."""
    reading = {"vendor": None, "name": "PLA - White", "material": "PLA", "weight_g": None}
    exact = score_candidate(reading, vendor="FlashForge", name="PLA - White", material="PLA", weight_g=1000)
    plain = score_candidate(reading, vendor="3DJAKE", name="White", material="PLA", weight_g=1000)
    assert exact > plain


def test_catalog_ranking_keeps_the_tie_break_that_rounding_would_lose(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both rows show 58 %, but "PLA - Black" scores higher and must come first whatever the file order."""
    entries = [
        _catalog_entry("plain", "3DJAKE", "Black", "PLA", 1000),
        _catalog_entry("flashforge", "FlashForge", "PLA - Black", "PLA", 1000),
    ]
    monkeypatch.setattr(spoolintake, "load_catalog", lambda: entries)

    matches = spoolintake.match_catalog({"vendor": None, "name": "PLA Black", "material": "PLA", "weight_g": None})

    assert [m["external_id"] for m in matches] == ["flashforge", "plain"]
    assert matches[0]["match_percent"] == matches[1]["match_percent"], "the shown percentage is the same"


def test_library_ranking_keeps_the_tie_break_that_rounding_would_lose() -> None:
    rows = [
        {"filament_id": 1, "vendor": "3DJAKE", "name": "Black", "material": "PLA", "weight_g": 1000},
        {"filament_id": 2, "vendor": "FlashForge", "name": "PLA - Black", "material": "PLA", "weight_g": 1000},
    ]
    reading = {"vendor": None, "name": "PLA Black", "material": "PLA", "weight_g": None}

    ranked = spoolintake._rank_library(rows, reading, {})  # noqa: SLF001

    assert [r["filament_id"] for r in ranked] == [2, 1]


def test_a_short_generic_candidate_gets_no_word_bonus() -> None:
    """The reverse direction must not lift every maker's plain "Green" for a reading of "Si1k Green"."""
    generic = score_candidate(
        {"vendor": None, "name": "Si1k Green", "material": "PLA", "weight_g": 1000},
        vendor="Abaflex",
        name="Green",
        material="PLA",
        weight_g=1000,
    )
    right = score_candidate(
        {"vendor": None, "name": "Si1k Green", "material": "PLA", "weight_g": 1000},
        vendor="Bambu Lab",
        name="Silk Green",
        material="PLA",
        weight_g=1000,
    )
    assert right > generic


def test_name_containment_matches_verbose_catalog_names() -> None:
    score = score_candidate(
        _EXTRACTION,
        vendor="Prusa Polymers",
        name="Prusament PLA Galaxy Black",
        material="PLA",
        weight_g=1000,
    )
    assert score >= 0.6


def test_unrelated_candidate_scores_low() -> None:
    score = score_candidate(_EXTRACTION, vendor="eSun", name="Warm White", material="ABS", weight_g=500)
    assert score < spoolintake._LIBRARY_MIN_SCORE  # noqa: SLF001


# --- Diameter mismatch penalty ------------------------------------------------------
#
# score_candidate ignored diameter entirely, so the 1.75 mm and 2.85 mm rows of the same
# product tied and catalogue order alone decided which one a scan matched. A small penalty
# now breaks that tie in favour of the reading's own size, without being able to push a
# genuinely better match off the shortlist.

_TWIN_ARGS = {"vendor": "Prusament", "name": "Galaxy Black", "material": "PLA", "weight_g": 1000}


def _twin_extraction(diameter_mm: object) -> dict:
    return {**_EXTRACTION, "diameter_mm": diameter_mm}


def test_diameter_mismatch_penalizes_the_other_size() -> None:
    reading_175 = _twin_extraction(1.75)
    score_175 = score_candidate(reading_175, diameter_mm=1.75, **_TWIN_ARGS)
    score_285 = score_candidate(reading_175, diameter_mm=2.85, **_TWIN_ARGS)
    assert score_175 > score_285
    assert score_175 - score_285 == pytest.approx(spoolintake._DIAMETER_MISMATCH_PENALTY)  # noqa: SLF001

    reading_285 = _twin_extraction(2.85)
    score_175_b = score_candidate(reading_285, diameter_mm=1.75, **_TWIN_ARGS)
    score_285_b = score_candidate(reading_285, diameter_mm=2.85, **_TWIN_ARGS)
    assert score_285_b > score_175_b


@pytest.mark.parametrize("catalogue_order", [("175", "285"), ("285", "175")])
def test_match_catalog_prefers_the_readings_diameter_whatever_the_catalogue_order(
    monkeypatch: pytest.MonkeyPatch,
    catalogue_order: tuple[str, str],
) -> None:
    entry_175 = _catalog_entry("twin-175", "Prusament", "Galaxy Black", "PLA", 1000)
    entry_175["diameter"] = 1.75
    entry_285 = _catalog_entry("twin-285", "Prusament", "Galaxy Black", "PLA", 1000)
    entry_285["diameter"] = 2.85
    by_id = {"175": entry_175, "285": entry_285}
    entries = [by_id[key] for key in catalogue_order]
    monkeypatch.setattr(spoolintake, "load_catalog", lambda: entries)

    matches_175 = spoolintake.match_catalog(_twin_extraction(1.75))
    matches_285 = spoolintake.match_catalog(_twin_extraction(2.85))

    assert matches_175[0]["external_id"] == "twin-175"
    assert matches_285[0]["external_id"] == "twin-285"


@pytest.mark.parametrize("reading_diameter", [None, 0, "not a number"])
def test_no_penalty_when_the_readings_diameter_is_unknown(reading_diameter: object) -> None:
    extraction = _twin_extraction(reading_diameter)
    with_diameter = score_candidate(extraction, diameter_mm=2.85, **_TWIN_ARGS)
    without_keyword = score_candidate(extraction, **_TWIN_ARGS)
    assert with_diameter == without_keyword


@pytest.mark.parametrize("candidate_diameter", [None, 0, "not a number"])
def test_no_penalty_when_the_candidates_diameter_is_unknown(candidate_diameter: object) -> None:
    extraction = _twin_extraction(1.75)
    with_diameter = score_candidate(extraction, diameter_mm=candidate_diameter, **_TWIN_ARGS)
    without_keyword = score_candidate(extraction, **_TWIN_ARGS)
    assert with_diameter == without_keyword


def test_285_and_3mm_are_the_same_size_and_a_string_diameter_is_coerced() -> None:
    extraction = _twin_extraction(2.85)
    score_3mm = score_candidate(extraction, diameter_mm=3.0, **_TWIN_ARGS)
    score_285 = score_candidate(extraction, diameter_mm=2.85, **_TWIN_ARGS)
    assert score_3mm == score_285

    score_string = score_candidate(_twin_extraction("1.75"), diameter_mm="1.75", **_TWIN_ARGS)
    score_number = score_candidate(_twin_extraction(1.75), diameter_mm=1.75, **_TWIN_ARGS)
    assert score_string == score_number


def test_a_penalised_exact_match_still_clears_both_thresholds() -> None:
    score = score_candidate(_twin_extraction(1.75), diameter_mm=2.85, **_TWIN_ARGS)
    assert score >= spoolintake._CATALOG_MIN_SCORE  # noqa: SLF001
    assert score >= spoolintake._LIBRARY_MIN_SCORE  # noqa: SLF001


def test_the_penalty_never_makes_a_score_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spoolintake, "_DIAMETER_MISMATCH_PENALTY", 999.0)
    score = score_candidate(
        {"vendor": None, "name": None, "material": None, "weight_g": None, "diameter_mm": 1.75},
        vendor=None,
        name=None,
        material=None,
        weight_g=None,
        diameter_mm=2.85,
    )
    assert score == 0.0


def test_rank_library_orders_twins_by_diameter_and_tolerates_missing_diameter() -> None:
    rows = [
        {
            "filament_id": 1,
            "vendor": "Prusament",
            "name": "Galaxy Black",
            "material": "PLA",
            "weight_g": 1000,
            "diameter_mm": 1.75,
        },
        {
            "filament_id": 2,
            "vendor": "Prusament",
            "name": "Galaxy Black",
            "material": "PLA",
            "weight_g": 1000,
            "diameter_mm": 2.85,
        },
        {
            # No diameter_mm key at all -- older rows and any that .get() must tolerate.
            "filament_id": 3,
            "vendor": "Prusament",
            "name": "Galaxy Black",
            "material": "PLA",
            "weight_g": 1000,
        },
    ]
    reading = _twin_extraction(2.85)

    ranked = spoolintake._rank_library(rows, reading, {})  # noqa: SLF001

    assert ranked[0]["filament_id"] == 2, "the matching size comes first"
    assert {r["filament_id"] for r in ranked} == {1, 2, 3}


def test_without_the_penalty_catalogue_order_alone_decides_the_twin_tie(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirms the penalty -- not something else -- is what orders the twins above.

    With the penalty zeroed the two otherwise-identical rows tie exactly, and ``_best``'s
    documented tie-break (stable sort, input order kept) takes over: whichever twin is listed
    first in the catalogue wins, regardless of the reading's diameter.
    """
    monkeypatch.setattr(spoolintake, "_DIAMETER_MISMATCH_PENALTY", 0.0)
    entry_175 = _catalog_entry("twin-175", "Prusament", "Galaxy Black", "PLA", 1000)
    entry_175["diameter"] = 1.75
    entry_285 = _catalog_entry("twin-285", "Prusament", "Galaxy Black", "PLA", 1000)
    entry_285["diameter"] = 2.85
    monkeypatch.setattr(spoolintake, "load_catalog", lambda: [entry_175, entry_285])

    matches = spoolintake.match_catalog(_twin_extraction(2.85))

    assert matches[0]["external_id"] == "twin-175", "catalogue order wins once the penalty is gone"


# --- Catalog matching --------------------------------------------------------------


def _catalog_entry(entry_id: str, manufacturer: str, name: str, material: str, weight: float) -> dict:
    return {
        "id": entry_id,
        "manufacturer": manufacturer,
        "name": name,
        "material": material,
        "weight": weight,
        "diameter": 1.75,
        "density": 1.24,
    }


def test_match_catalog_ranks_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = [
        _catalog_entry("exact", "Prusament", "Galaxy Black", "PLA", 1000),
        _catalog_entry("wrong-material", "Prusament", "Galaxy Black", "PETG", 1000),
        _catalog_entry("other", "eSun", "Cold White", "ABS", 500),
        *[_catalog_entry(f"variant-{i}", "Prusament", f"Galaxy Black {i}", "PLA", 1000) for i in range(6)],
    ]
    monkeypatch.setattr(spoolintake, "load_catalog", lambda: entries)

    matches = spoolintake.match_catalog(_EXTRACTION)

    assert matches[0]["external_id"] == "exact"
    assert len(matches) == spoolintake._MATCH_LIMIT  # noqa: SLF001
    assert all(match["kind"] == "catalog" for match in matches)
    assert "wrong-material" not in [match["external_id"] for match in matches]


def test_load_catalog_reads_and_caches_by_mtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    catalog_file = tmp_path / "filaments.json"
    catalog_file.write_text(json.dumps([_catalog_entry("a", "X", "Y", "PLA", 1000)]))
    monkeypatch.setattr(spoolintake.externaldb, "get_filaments_file", lambda: catalog_file)
    monkeypatch.setattr(spoolintake, "_catalog_cache", spoolintake._CatalogCache())  # noqa: SLF001

    first = spoolintake.load_catalog()
    assert [entry["id"] for entry in first] == ["a"]
    # Same mtime: served from cache (identity check).
    assert spoolintake.load_catalog() is first


def test_load_catalog_degrades_to_empty(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    monkeypatch.setattr(spoolintake.externaldb, "get_filaments_file", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(spoolintake, "_catalog_cache", spoolintake._CatalogCache())  # noqa: SLF001
    assert spoolintake.load_catalog() == []

    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    monkeypatch.setattr(spoolintake.externaldb, "get_filaments_file", lambda: broken)
    assert spoolintake.load_catalog() == []


# --- Domain validation of extractions (#380) ---------------------------------------
#
# Every value below was actually returned by a local vision model reading a real label photo.
# A wrong value is worse than a missing one: `name`/`vendor`/`material`/`weight_g` are the only
# fields score_candidate weights, so a confident mistake there drags the match toward the wrong
# record, and the temperatures get written to the spool the user saves.
#
# The rules therefore *drop* rather than guess, and the second half of these tests is the more
# important half: real, correct values must survive untouched.


def test_a_diameter_misread_as_a_weight_is_dropped() -> None:
    """qwen/gemma both read "1.75MM" off the label and returned it as weight_g=1750.

    Targeted at the actual failure rather than a general plausibility band: 1750 g is not an
    absurd weight in the abstract, which is exactly why a range check would not catch it. What
    gives it away is that it equals the diameter x 1000.
    """
    out = spoolintake.normalize_extraction({"weight_g": 1750, "diameter_mm": 1.75})
    assert out["weight_g"] is None
    assert out["diameter_mm"] == 1.75


def test_a_real_spool_weight_is_kept_even_alongside_a_diameter() -> None:
    out = spoolintake.normalize_extraction({"weight_g": 1000, "diameter_mm": 1.75})
    assert out["weight_g"] == 1000


def test_an_impossible_filament_diameter_is_dropped() -> None:
    assert spoolintake.normalize_extraction({"diameter_mm": 17.5})["diameter_mm"] is None


@pytest.mark.parametrize("diameter", [1.75, 2.85, 3.0])
def test_the_three_real_filament_diameters_survive(diameter: float) -> None:
    assert spoolintake.normalize_extraction({"diameter_mm": diameter})["diameter_mm"] == diameter


def test_temperatures_impossible_for_the_stated_material_are_dropped() -> None:
    """gemma4:e2b returned 65/50 for a PETG label reading 240/90.

    Only the nozzle value dies. 65 C will not melt PETG at all, so it is certainly a misread;
    a 50 C bed is *low* for PETG but people really do print it there, and the rule deliberately
    stops at impossible rather than unusual. Catching one of the two wrong values is the correct
    outcome -- widening the window to catch the second would start discarding real ones.
    """
    out = spoolintake.normalize_extraction({"material": "PETG", "extruder_temp_c": 65, "bed_temp_c": 50})
    assert out["extruder_temp_c"] is None
    assert out["bed_temp_c"] == 50
    assert out["material"] == "PETG"


def test_a_bed_temperature_no_pla_printer_uses_is_dropped() -> None:
    """qwen2.5vl:7b returned bed_temp_c=220 for a PLA spool -- hot enough to melt the print."""
    out = spoolintake.normalize_extraction({"material": "PLA", "extruder_temp_c": 210, "bed_temp_c": 220})
    assert out["bed_temp_c"] is None
    assert out["extruder_temp_c"] == 210, "the nozzle temperature was fine and must survive"


def test_correct_temperatures_survive_for_each_material() -> None:
    for material, nozzle, bed in (("PLA", 210, 60), ("PETG", 240, 90), ("ABS", 250, 100), ("TPU", 220, 40)):
        out = spoolintake.normalize_extraction(
            {"material": material, "extruder_temp_c": nozzle, "bed_temp_c": bed},
        )
        assert out["extruder_temp_c"] == nozzle, f"{material} nozzle {nozzle} was wrongly dropped"
        assert out["bed_temp_c"] == bed, f"{material} bed {bed} was wrongly dropped"


def test_temperatures_are_kept_when_the_material_is_unknown() -> None:
    """With no material there is nothing to validate against -- do not invent a verdict."""
    out = spoolintake.normalize_extraction({"extruder_temp_c": 240, "bed_temp_c": 90})
    assert out["extruder_temp_c"] == 240
    assert out["bed_temp_c"] == 90


def test_the_material_repeated_as_the_name_is_dropped() -> None:
    """gemma4:e2b put "PETG" in name on a label whose product name was "Jet Black"."""
    out = spoolintake.normalize_extraction({"name": "PETG", "material": "PETG"})
    assert out["name"] is None
    assert out["material"] == "PETG"


def test_a_colour_name_echoed_into_vendor_is_dropped() -> None:
    """gemma4:e2b returned vendor="FIRE ENGINE RED" -- the colour, in a 0.3-weighted match field."""
    out = spoolintake.normalize_extraction({"vendor": "FIRE ENGINE RED", "name": "FIRE ENGINE RED"})
    assert out["vendor"] is None
    assert out["name"] == "FIRE ENGINE RED"


def test_a_weight_string_captured_as_vendor_is_dropped() -> None:
    """gemma4:e2b returned vendor="SILVER-1KG(N.W)" with confidence "high"."""
    assert spoolintake.normalize_extraction({"vendor": "SILVER-1KG(N.W)"})["vendor"] is None


@pytest.mark.parametrize("vendor", ["Prusa Polymers", "eSUN", "ELEGOO", "Generic", "Polymaker", "3DJAKE"])
def test_real_vendors_survive(vendor: str) -> None:
    """The rule must not require catalog membership.

    "Prusa Polymers" is the correct vendor for a Prusament label but is not the catalog's
    spelling, and small brands are absent entirely -- dropping anything unrecognised would
    discard right answers to catch wrong ones.
    """
    assert spoolintake.normalize_extraction({"vendor": vendor})["vendor"] == vendor


# --- Decision-model rerank ---


@pytest.fixture(autouse=True)
def _clean_decision_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the SPOOLMAN_AI_DECISION_* env between tests in this module."""
    for name in (decision.ENV_BASE_URL, decision.ENV_API_KEY, decision.ENV_MODEL):
        monkeypatch.delenv(name, raising=False)


_DECISION_CONFIG = decision.DecisionConfig(base_url="https://api.typesafe.ai", model="jev-1.13")


def _library_candidate(filament_id: int, match_percent: int) -> dict:
    return {
        "kind": "library",
        "filament_id": filament_id,
        "vendor": "Prusa",
        "name": "Galaxy Black",
        "material": "PLA",
        "weight_g": 1000,
        "active_spool_count": 0,
        "remaining_weight_g": 1000.0,
        "match_percent": match_percent,
    }


def _rerank_answer_body(*, choices: dict[str, tuple[str, dict[str, float]]]) -> dict:
    """Build a System One response answering each requested id with the given choice."""
    return {
        "model": "jev-1.13.0",
        "answers": {
            qid: {"type": "choice", "choice": choice, "probabilities": probabilities, "confidence": 0.9}
            for qid, (choice, probabilities) in choices.items()
        },
        "usage": {},
    }


_FULL_EXTRACTION = {
    "vendor": "Prusa",
    "name": "Galaxy Black",
    "material": "PLA",
    "color_hex": "1a1a2e",
    "weight_g": 1000,
    "spool_weight_g": 250,
    "diameter_mm": 1.75,
    "extruder_temp_c": 210,
    "bed_temp_c": 60,
    "lot_nr": "L123",
    "article_number": "A1",
    "confidence": "high",
}


@respx.mock
async def test_rerank_matches_reorders_by_probability_and_keeps_match_percent() -> None:
    c1, c2 = _library_candidate(1, match_percent=90), _library_candidate(2, match_percent=40)
    matches = {"library": [c1, c2], "catalog": []}
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(
            200,
            json=_rerank_answer_body(
                choices={"library": ("c2", {"c1": 0.2, "c2": 0.7, "none": 0.1})},
            ),
        ),
    )

    result = await spoolintake.rerank_matches(_DECISION_CONFIG, _FULL_EXTRACTION, matches)

    assert [c["filament_id"] for c in result["library"]] == [2, 1]
    assert result["library"][0]["rerank_probability"] == 0.7
    assert result["library"][1]["rerank_probability"] == 0.2
    assert result["library"][0]["match_percent"] == 40, "match_percent stays the fuzzy score"
    assert result["library"][1]["match_percent"] == 90
    assert result["catalog"] == []


@respx.mock
async def test_rerank_matches_is_stable_for_ties() -> None:
    c1, c2, c3 = (
        _library_candidate(1, match_percent=90),
        _library_candidate(2, match_percent=80),
        _library_candidate(3, match_percent=70),
    )
    matches = {"library": [c1, c2, c3], "catalog": []}
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(
            200,
            json=_rerank_answer_body(
                choices={"library": ("none", {"c1": 0.5, "c2": 0.5, "c3": 0.5, "none": 0.0})},
            ),
        ),
    )

    result = await spoolintake.rerank_matches(_DECISION_CONFIG, _FULL_EXTRACTION, matches)

    assert [c["filament_id"] for c in result["library"]] == [1, 2, 3], "ties keep the original (fuzzy) order"


@respx.mock
async def test_rerank_matches_leaves_empty_lists_alone_and_asks_no_question_for_them() -> None:
    c1 = _library_candidate(1, match_percent=90)
    matches = {"library": [c1], "catalog": []}
    route = respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(
            200,
            json=_rerank_answer_body(choices={"library": ("c1", {"c1": 1.0, "none": 0.0})}),
        ),
    )

    result = await spoolintake.rerank_matches(_DECISION_CONFIG, _FULL_EXTRACTION, matches)

    assert result["catalog"] == []
    sent = json.loads(route.calls.last.request.content)
    assert set(sent["questions"]) == {"library"}


@respx.mock
async def test_rerank_matches_sends_no_request_when_both_lists_are_empty() -> None:
    matches = {"library": [], "catalog": []}

    result = await spoolintake.rerank_matches(_DECISION_CONFIG, _FULL_EXTRACTION, matches)

    assert result == matches


@respx.mock
async def test_rerank_matches_sends_no_request_without_identifying_fields() -> None:
    c1 = _library_candidate(1, match_percent=90)
    matches = {"library": [c1], "catalog": []}
    bare_extraction = dict.fromkeys(_FULL_EXTRACTION)

    result = await spoolintake.rerank_matches(_DECISION_CONFIG, bare_extraction, matches)

    assert result == matches


@respx.mock
async def test_rerank_matches_state_only_carries_the_four_identifying_fields() -> None:
    c1 = _library_candidate(1, match_percent=90)
    matches = {"library": [c1], "catalog": []}
    route = respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=Response(
            200,
            json=_rerank_answer_body(choices={"library": ("c1", {"c1": 1.0, "none": 0.0})}),
        ),
    )

    await spoolintake.rerank_matches(_DECISION_CONFIG, _FULL_EXTRACTION, matches)

    sent = json.loads(route.calls.last.request.content)
    assert sent["state"] == {"vendor": "Prusa", "name": "Galaxy Black", "material": "PLA", "weight_g": 1000}


def test_apply_rerank_keeps_the_fuzzy_order_on_a_none_answer_even_with_higher_probabilities() -> None:
    """A "none" answer must not let a lower-ranked candidate's probability promote it.

    The client preselects the first (fuzzy-ranked) entry, so reordering on a rejected answer
    would be worse than leaving the fuzzy order alone.
    """
    c1, c2 = _library_candidate(1, match_percent=90), _library_candidate(2, match_percent=40)
    answer = decision.ChoiceAnswer(
        choice="none",
        probabilities={"c1": 0.1, "c2": 0.3, "none": 0.6},
        confidence=None,
    )

    result = spoolintake._apply_rerank([c1, c2], answer)  # noqa: SLF001

    assert [c["filament_id"] for c in result] == [1, 2], "fuzzy order is kept despite c2's higher probability"
    assert result[0]["rerank_probability"] == 0.1
    assert result[1]["rerank_probability"] == 0.3


def test_apply_rerank_with_no_probabilities_puts_the_chosen_candidate_first() -> None:
    c1, c2, c3 = (
        _library_candidate(1, match_percent=90),
        _library_candidate(2, match_percent=80),
        _library_candidate(3, match_percent=70),
    )
    answer = decision.ChoiceAnswer(choice="c2", probabilities={}, confidence=None)

    result = spoolintake._apply_rerank([c1, c2, c3], answer)  # noqa: SLF001

    assert [c["filament_id"] for c in result] == [2, 1, 3]


# --- build_matches: reranking integration -----------------------------------------


@respx.mock
async def test_build_matches_makes_no_http_call_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    fuzzy_library = [_library_candidate(1, match_percent=90)]

    async def _fake_match_library(db: object, extraction: dict) -> list[dict]:  # noqa: ARG001
        return fuzzy_library

    def _fake_match_catalog(extraction: dict) -> list[dict]:  # noqa: ARG001
        return []

    monkeypatch.setattr(spoolintake, "match_library", _fake_match_library)
    monkeypatch.setattr(spoolintake, "match_catalog", _fake_match_catalog)

    result = await spoolintake.build_matches(None, _FULL_EXTRACTION)

    assert result == {"library": fuzzy_library, "catalog": []}


@respx.mock
async def test_build_matches_keeps_fuzzy_order_and_warns_on_decision_endpoint_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai")
    fuzzy_library = [_library_candidate(1, match_percent=90), _library_candidate(2, match_percent=40)]

    async def _fake_match_library(db: object, extraction: dict) -> list[dict]:  # noqa: ARG001
        return fuzzy_library

    def _fake_match_catalog(extraction: dict) -> list[dict]:  # noqa: ARG001
        return []

    monkeypatch.setattr(spoolintake, "match_library", _fake_match_library)
    monkeypatch.setattr(spoolintake, "match_catalog", _fake_match_catalog)
    respx.post("https://api.typesafe.ai/v1/systemone").mock(return_value=Response(500))

    with caplog.at_level("WARNING"):
        result = await spoolintake.build_matches(None, _FULL_EXTRACTION)

    assert result == {"library": fuzzy_library, "catalog": []}
    assert "Keeping the fuzzy match order" in caplog.text


@respx.mock
async def test_build_matches_keeps_fuzzy_order_and_warns_when_resolve_config_raises(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An optional reorder must never break Scan-to-Spool, even on a bug in resolve_config."""
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai")
    fuzzy_library = [_library_candidate(1, match_percent=90), _library_candidate(2, match_percent=40)]

    async def _fake_match_library(db: object, extraction: dict) -> list[dict]:  # noqa: ARG001
        return fuzzy_library

    def _fake_match_catalog(extraction: dict) -> list[dict]:  # noqa: ARG001
        return []

    def _raise_resolve_config() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(spoolintake, "match_library", _fake_match_library)
    monkeypatch.setattr(spoolintake, "match_catalog", _fake_match_catalog)
    monkeypatch.setattr(decision, "resolve_config", _raise_resolve_config)

    with caplog.at_level("WARNING"):
        result = await spoolintake.build_matches(None, _FULL_EXTRACTION)

    assert result == {"library": fuzzy_library, "catalog": []}
    assert "unexpected error" in caplog.text


@respx.mock
async def test_build_matches_keeps_fuzzy_order_and_warns_when_rerank_matches_raises_unexpectedly(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai")
    fuzzy_library = [_library_candidate(1, match_percent=90), _library_candidate(2, match_percent=40)]

    async def _fake_match_library(db: object, extraction: dict) -> list[dict]:  # noqa: ARG001
        return fuzzy_library

    def _fake_match_catalog(extraction: dict) -> list[dict]:  # noqa: ARG001
        return []

    async def _raise_rerank_matches(config: object, extraction: dict, matches: dict) -> dict:  # noqa: ARG001
        raise ValueError("boom")

    monkeypatch.setattr(spoolintake, "match_library", _fake_match_library)
    monkeypatch.setattr(spoolintake, "match_catalog", _fake_match_catalog)
    monkeypatch.setattr(spoolintake, "rerank_matches", _raise_rerank_matches)

    with caplog.at_level("WARNING"):
        result = await spoolintake.build_matches(None, _FULL_EXTRACTION)

    assert result == {"library": fuzzy_library, "catalog": []}
    assert "unexpected error" in caplog.text


@respx.mock
async def test_build_matches_keeps_fuzzy_order_and_makes_no_http_call_with_an_invalid_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "http://[::1")
    fuzzy_library = [_library_candidate(1, match_percent=90)]

    async def _fake_match_library(db: object, extraction: dict) -> list[dict]:  # noqa: ARG001
        return fuzzy_library

    def _fake_match_catalog(extraction: dict) -> list[dict]:  # noqa: ARG001
        return []

    monkeypatch.setattr(spoolintake, "match_library", _fake_match_library)
    monkeypatch.setattr(spoolintake, "match_catalog", _fake_match_catalog)
    route = respx.post(url__regex=r".*").mock(return_value=Response(200))

    result = await spoolintake.build_matches(None, _FULL_EXTRACTION)

    assert result == {"library": fuzzy_library, "catalog": []}
    assert route.call_count == 0


async def test_build_matches_propagates_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The catch-all around the rerank must not swallow a cancelled scan."""
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai")
    candidate = _library_candidate(1, match_percent=90)

    async def fake_library(_db: object, _extraction: dict) -> list[dict]:
        return [candidate]

    started = asyncio.Event()

    async def hanging_ask(*_args: object, **_kwargs: object) -> dict:
        started.set()
        await asyncio.sleep(10)
        return {}

    monkeypatch.setattr(spoolintake, "match_library", fake_library)
    monkeypatch.setattr(spoolintake, "match_catalog", lambda _extraction: [])
    monkeypatch.setattr(decision, "ask_choices", hanging_ask)

    task = asyncio.create_task(spoolintake.build_matches(None, _FULL_EXTRACTION))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_apply_rerank_sorts_on_unrounded_probabilities() -> None:
    """Two probabilities that round to the same value still follow the model's order."""
    candidates = [_library_candidate(1, match_percent=90), _library_candidate(2, match_percent=80)]
    answer = decision.ChoiceAnswer(choice="c2", probabilities={"c1": 0.5004, "c2": 0.5005}, confidence=0.5)

    ranked = spoolintake._apply_rerank(candidates, answer)  # noqa: SLF001

    assert [c["filament_id"] for c in ranked] == [2, 1]
    assert ranked[0]["rerank_probability"] == ranked[1]["rerank_probability"] == 0.5
