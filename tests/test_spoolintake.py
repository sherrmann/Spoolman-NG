"""Unit tests for Scan-to-Spool intake (#361): reply parsing, normalization, matching.

Oracle strategy: the extraction parser is driven through realistic model-reply shapes
(fences, prose, malformed JSON); normalization through the unit traps a label photo
actually produces (kg-as-grams, "1.75 mm" strings, #-prefixed hex); the matcher through
its pure scoring function and an injected catalog — no DB, no network, no LLM anywhere.
"""

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
