"""Scoring and CLI logic of scripts/duplicate_eval.py (`poe duplicate-eval`).

The eval needs a live decision endpoint for the model tier, so it is out of CI; these tests feed
its scoring logic hand-made results and a stubbed endpoint instead.
"""

import dataclasses
import importlib.util
import json
import random
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from spoolman import decision, duplicates
from spoolman import math as colour_math

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "duplicate_eval.py"

#: A tiny inline catalogue: two colours of one Acme PLA line (siblings for the "other colour"
#: negative), a second Acme line of a different material (for the "different product" negative),
#: and an unrelated single-line manufacturer (never eligible for a "different product" negative).
_TINY_CATALOG = [
    {
        "id": "acme-pla-red",
        "manufacturer": "Acme",
        "name": "Red",
        "material": "PLA",
        "diameter": 1.75,
        "weight": 1000,
        "color_hex": "FF0000",
        "color_hexes": None,
    },
    {
        "id": "acme-pla-blue",
        "manufacturer": "Acme",
        "name": "Blue",
        "material": "PLA",
        "diameter": 1.75,
        "weight": 1000,
        "color_hex": "0000FF",
        "color_hexes": None,
    },
    {
        "id": "acme-petg-speedy",
        "manufacturer": "Acme",
        "name": "Speedy",
        "material": "PETG",
        "diameter": 1.75,
        "weight": 1000,
        "color_hex": "00FF00",
        "color_hexes": None,
    },
    {
        "id": "beta-abs-solo",
        "manufacturer": "Beta",
        "name": "Solo",
        "material": "ABS",
        "diameter": 1.75,
        "weight": 1000,
        "color_hex": "111111",
        "color_hexes": None,
    },
]


@pytest.fixture
def eval_module() -> Iterator[ModuleType]:
    """Import the script by path (it is a standalone script, not an installed package)."""
    spec = importlib.util.spec_from_file_location("_duplicate_eval_under_test", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("_duplicate_eval_under_test", None)


def _answer(choice: str, probability: float | None) -> decision.ChoiceAnswer:
    probabilities = {choice: probability} if probability is not None else {}
    return decision.ChoiceAnswer(choice=choice, probabilities=probabilities, confidence=None)


# --- CaseResult.model_pick -------------------------------------------------------------------


def test_model_pick_returns_the_exact_match_without_asking_the_model(eval_module: ModuleType) -> None:
    result = eval_module.CaseResult("Bambu Lab", "Bambu Lab", "Bambu Lab", None, None)

    assert result.model_pick(0.5) == "Bambu Lab"


def test_model_pick_returns_none_when_the_model_was_not_asked(eval_module: ModuleType) -> None:
    result = eval_module.CaseResult("Sunlu", None, None, None, None)

    assert result.model_pick(0.5) is None


def test_model_pick_returns_none_for_a_none_answer(eval_module: ModuleType) -> None:
    candidates = [duplicates.Match(id=0, name="Bambu Lab")]
    result = eval_module.CaseResult("Bambu", "Bambu Lab", None, candidates, _answer(duplicates._NONE, None))  # noqa: SLF001

    assert result.model_pick(0.5) is None


def test_model_pick_respects_the_threshold(eval_module: ModuleType) -> None:
    candidates = [duplicates.Match(id=0, name="eSUN")]
    result = eval_module.CaseResult("eSUN 3D", "eSUN", None, candidates, _answer("v0", 0.65))

    assert result.model_pick(0.6) == "eSUN"
    assert result.model_pick(0.7) is None, "below the threshold: no suggestion"


def test_model_pick_falls_back_to_confidence_when_no_probability_is_given(eval_module: ModuleType) -> None:
    candidates = [duplicates.Match(id=0, name="eSUN")]
    answer = decision.ChoiceAnswer(choice="v0", probabilities={}, confidence=0.8)
    result = eval_module.CaseResult("eSUN 3D", "eSUN", None, candidates, answer)

    assert result.model_pick(0.7) == "eSUN"
    assert result.model_pick(0.9) is None


# --- _run_case ---------------------------------------------------------------------------------


async def test_run_case_uses_the_exact_tier_and_skips_the_model(eval_module: ModuleType) -> None:
    case = {"typed": "eSUN", "expected": "eSUN", "existing": ["eSUN", "Polymaker"]}
    config = decision.DecisionConfig(base_url="https://api.typesafe.ai", model="jev-latest")

    result = await eval_module._run_case(config, case)  # noqa: SLF001

    assert result.exact == "eSUN"
    assert result.candidates is None, "an exact match short-circuits the model, as similar_vendor does"
    assert result.answer is None


async def test_run_case_baseline_only_never_calls_the_model(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = {"typed": "eSUN 3D", "expected": "eSUN", "existing": ["eSUN", "Polymaker"]}

    async def explode(*_args: object, **_kwargs: object) -> dict:
        msg = "ask_choices must not be called with config=None"
        raise AssertionError(msg)

    monkeypatch.setattr(decision, "ask_choices", explode)

    result = await eval_module._run_case(None, case)  # noqa: SLF001

    assert result.exact is None
    assert result.candidates is None
    assert result.answer is None


async def test_run_case_asks_the_model_when_there_is_no_exact_match(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = {"typed": "Bambu", "expected": "Bambu Lab", "existing": ["Bambu Lab", "Polymaker"]}
    config = decision.DecisionConfig(base_url="https://api.typesafe.ai", model="jev-latest")

    async def stub_ask(_config: object, state: object, questions: dict) -> dict:
        assert state == "Bambu"
        assert "vendor" in questions
        return {"vendor": _answer("v0", 0.9)}

    monkeypatch.setattr(decision, "ask_choices", stub_ask)

    result = await eval_module._run_case(config, case)  # noqa: SLF001

    assert result.exact is None
    assert result.candidates is not None
    assert result.answer.choice == "v0"
    assert result.model_pick(0.6) == "Bambu Lab"


async def test_run_case_records_a_decision_error_without_raising(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = {"typed": "Bambu", "expected": "Bambu Lab", "existing": ["Bambu Lab", "Polymaker"]}
    config = decision.DecisionConfig(base_url="https://api.typesafe.ai", model="jev-latest")

    async def failing(*_args: object, **_kwargs: object) -> dict:
        raise decision.DecisionError("HTTP 429")

    monkeypatch.setattr(decision, "ask_choices", failing)

    result = await eval_module._run_case(config, case)  # noqa: SLF001

    assert result.error == "HTTP 429"
    assert result.answer is None
    assert result.model_pick(0.5) is None


# --- _score --------------------------------------------------------------------------------


def _result(eval_module: ModuleType, typed: str, expected: str | None, exact: str | None) -> object:
    return eval_module.CaseResult(typed, expected, exact, None, None)


def test_score_counts_true_positives_and_recall(eval_module: ModuleType) -> None:
    results = [
        _result(eval_module, "eSUN", "eSUN", "eSUN"),
        _result(eval_module, "Bambu", "Bambu Lab", None),  # missed: not a warning at all
        _result(eval_module, "PolyLite", None, None),  # correctly silent
    ]

    scores = eval_module._score(results, lambda r: r.exact)  # noqa: SLF001

    assert scores.precision == 1.0
    assert scores.recall == 0.5
    assert scores.false_warning_rate == 0.0
    assert scores.wrong == ["Bambu"]


def test_score_counts_a_wrong_pick_on_a_positive_case_as_a_false_positive(eval_module: ModuleType) -> None:
    results = [_result(eval_module, "PolyLite", "Polymaker", "Not Polymaker")]

    scores = eval_module._score(results, lambda r: r.exact)  # noqa: SLF001

    assert scores.precision == 0.0
    assert scores.recall == 0.0


def test_score_counts_a_warning_on_a_negative_case_as_a_false_warning(eval_module: ModuleType) -> None:
    results = [_result(eval_module, "PolyLite", None, "Polymaker")]

    scores = eval_module._score(results, lambda r: r.exact)  # noqa: SLF001

    assert scores.false_warning_rate == 1.0
    assert scores.precision == 0.0
    assert scores.recall is None, "no positive cases: recall is undefined"


def test_score_precision_is_none_with_no_warnings_at_all(eval_module: ModuleType) -> None:
    results = [_result(eval_module, "Bambu", "Bambu Lab", None)]

    scores = eval_module._score(results, lambda r: r.exact)  # noqa: SLF001

    assert scores.precision is None
    assert scores.recall == 0.0


# --- _print_report / _main -----------------------------------------------------------------


def test_print_report_shows_both_tiers(eval_module: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    candidates = [duplicates.Match(id=0, name="Bambu Lab")]
    results = [
        eval_module.CaseResult("eSUN", "eSUN", "eSUN", None, None),
        eval_module.CaseResult("Bambu", "Bambu Lab", None, candidates, _answer("v0", 0.65)),
        eval_module.CaseResult("PolyLite", None, None, None, None),
    ]

    eval_module._print_report(results)  # noqa: SLF001
    out = capsys.readouterr().out

    assert "3 cases (2 duplicates, 1 not)" in out
    assert "Code tier only (exact match)" in out
    assert "Code tier plus decision model, by probability threshold" in out
    assert "threshold 0.6" in out
    assert "threshold 0.7" in out
    assert "shipped threshold (0.6)" in out


async def test_main_baseline_only_needs_no_endpoint(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(decision.ENV_BASE_URL, raising=False)

    result = await eval_module._main(baseline_only=True)  # noqa: SLF001

    assert result == 0
    assert "Code tier only" in capsys.readouterr().out


async def test_main_without_baseline_only_needs_an_endpoint(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(decision.ENV_BASE_URL, raising=False)
    monkeypatch.delenv(decision.ENV_API_KEY, raising=False)
    monkeypatch.delenv(decision.ENV_MODEL, raising=False)

    result = await eval_module._main(baseline_only=False)  # noqa: SLF001

    assert result == 2
    assert "--baseline-only" in capsys.readouterr().err


async def test_main_fails_when_a_case_errors(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai")

    async def failing(*_args: object, **_kwargs: object) -> dict:
        raise decision.DecisionError("HTTP 429")

    monkeypatch.setattr(decision, "ask_choices", failing)

    result = await eval_module._main(baseline_only=False)  # noqa: SLF001

    assert result == 1
    assert "failed with a decision-endpoint error" in capsys.readouterr().out


# --- argument parsing ------------------------------------------------------------------------


def test_main_baseline_only_flag_is_parsed(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["duplicate_eval.py", "--baseline-only"])
    calls: list[bool] = []

    async def fake_main(*, baseline_only: bool) -> int:
        calls.append(baseline_only)
        return 0

    monkeypatch.setattr(eval_module, "_main", fake_main)

    with pytest.raises(SystemExit) as exit_info:
        eval_module.main()

    assert exit_info.value.code == 0
    assert calls == [True]


def test_main_defaults_to_needing_the_endpoint(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["duplicate_eval.py"])
    calls: list[bool] = []

    async def fake_main(*, baseline_only: bool) -> int:
        calls.append(baseline_only)
        return 0

    monkeypatch.setattr(eval_module, "_main", fake_main)

    with pytest.raises(SystemExit):
        eval_module.main()

    assert calls == [False]


# --- Filaments: small helpers ------------------------------------------------------------------


def test_entry_colours_reads_single_and_multi_hex(eval_module: ModuleType) -> None:
    single = eval_module._entry_colours({"color_hex": "ABCDEF", "color_hexes": None})  # noqa: SLF001
    multi = eval_module._entry_colours({"color_hex": None, "color_hexes": ["112233", "445566"]})  # noqa: SLF001

    assert single == ("abcdef",)
    assert multi == ("112233", "445566")


def test_draft_colour_fields_round_trips_through_filament_draft(eval_module: ModuleType) -> None:
    assert eval_module._draft_colour_fields(None) == (None, None)  # noqa: SLF001
    assert eval_module._draft_colour_fields(("ff0000",)) == ("ff0000", None)  # noqa: SLF001
    assert eval_module._draft_colour_fields(("ff0000", "00ff00")) == (None, "ff0000,00ff00")  # noqa: SLF001


def test_jitter_hex_stays_within_the_delta_e_budget(eval_module: ModuleType) -> None:
    rng = random.Random(11)  # noqa: S311

    jittered = eval_module._jitter_hex(rng, "336699")  # noqa: SLF001

    lab_a = colour_math.rgb_to_lab(colour_math.hex_to_rgb("336699"))
    lab_b = colour_math.rgb_to_lab(colour_math.hex_to_rgb(jittered))
    assert colour_math.delta_e(lab_a, lab_b) < 1.0


def test_noisy_name_never_empty_and_is_deterministic_for_a_seed(eval_module: ModuleType) -> None:
    result_a = eval_module._noisy_name(random.Random(42), "Almond", "PLA+", "3D-Fuel")  # noqa: SLF001, S311
    result_b = eval_module._noisy_name(random.Random(42), "Almond", "PLA+", "3D-Fuel")  # noqa: SLF001, S311

    assert result_a == result_b
    assert result_a.strip() != ""


# --- Filaments: case generation ----------------------------------------------------------------


def test_build_filament_dataset_is_deterministic_for_a_seed(eval_module: ModuleType) -> None:
    rows_a, cases_a = eval_module._build_filament_dataset(_TINY_CATALOG, seed=7, count=4)  # noqa: SLF001
    rows_b, cases_b = eval_module._build_filament_dataset(_TINY_CATALOG, seed=7, count=4)  # noqa: SLF001

    assert rows_a == rows_b
    assert [dataclasses.astuple(case) for case in cases_a] == [dataclasses.astuple(case) for case in cases_b]


def test_build_filament_dataset_library_rows_match_the_filament_rows_shape(eval_module: ModuleType) -> None:
    rows, _ = eval_module._build_filament_dataset(_TINY_CATALOG, seed=1, count=4)  # noqa: SLF001

    assert rows
    expected_keys = {"filament_id", "vendor_id", "vendor", "name", "material", "weight_g", "diameter_mm", "colours"}
    for row in rows:
        assert set(row) == expected_keys


def test_negative_colour_cases_use_a_genuinely_different_colour(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Noise-free so the drafted name still identifies which catalogue entry it came from.
    monkeypatch.setattr(eval_module, "_noisy_name", lambda _rng, name, _material, _vendor: name)
    rng = random.Random(5)  # noqa: S311
    by_group, _ = eval_module._group_catalog(_TINY_CATALOG)  # noqa: SLF001
    siblings = eval_module._colour_siblings(by_group)  # noqa: SLF001
    library_index: dict[str, int] = {}

    def add_to_library(entry: dict) -> int:
        library_index.setdefault(entry["id"], len(library_index))
        return library_index[entry["id"]]

    cases = eval_module._negative_colour_cases(rng, _TINY_CATALOG, siblings, set(), add_to_library, 5)  # noqa: SLF001

    assert cases
    by_name = {entry["name"]: entry for entry in _TINY_CATALOG}
    for case in cases:
        assert case.expected is None
        assert case.kind == "negative_colour"
        entry = by_name[case.draft.name]
        assert entry["id"] in library_index, "the library must hold the colour being warned about"
        # Either a real, genuinely different colour, or the colour left unset altogether; never
        # the library row's own colour (that would make it a real duplicate, not a negative case).
        original_colours = eval_module._entry_colours(entry)  # noqa: SLF001
        assert duplicates.colour_relation(case.colours, original_colours) in ("different colour", "colour unknown")
        has_hex = case.draft.color_hex is not None or case.draft.multi_color_hexes is not None
        assert has_hex == (case.colours is not None)


def test_negative_product_cases_pick_a_different_product_line(eval_module: ModuleType) -> None:
    rng = random.Random(3)  # noqa: S311
    _, by_manufacturer = eval_module._group_catalog(_TINY_CATALOG)  # noqa: SLF001
    multi_line = [
        name
        for name, entries in by_manufacturer.items()
        if len({eval_module._group_key(e) for e in entries}) > 1  # noqa: SLF001
    ]
    library_index: dict[str, int] = {}
    excluded_ids: set[str] = set()

    def add_to_library(entry: dict) -> int:
        library_index.setdefault(entry["id"], len(library_index))
        return library_index[entry["id"]]

    cases = eval_module._negative_product_cases(  # noqa: SLF001
        rng,
        by_manufacturer,
        multi_line,
        library_index,
        excluded_ids,
        add_to_library,
        5,
    )

    assert cases
    by_id = {entry["id"]: entry for entry in _TINY_CATALOG}
    for case in cases:
        assert case.expected is None
        assert case.kind == "negative_product"
        typed = next(e for e in _TINY_CATALOG if e["name"] == case.draft.name and e["material"] == case.draft.material)
        assert typed["id"] not in library_index, "the typed product itself must not already be in the library"
        library_entries = [by_id[eid] for eid in library_index]
        other_line_in_library = [
            e
            for e in library_entries
            if e["manufacturer"] == typed["manufacturer"] and eval_module._group_key(e) != eval_module._group_key(typed)  # noqa: SLF001
        ]
        assert other_line_in_library, "a different product line from the same manufacturer must be in the library"


def test_positive_cases_keep_the_same_colour_and_a_nonempty_name(eval_module: ModuleType) -> None:
    rng = random.Random(9)  # noqa: S311
    library_index: dict[str, int] = {}

    def add_to_library(entry: dict) -> int:
        library_index.setdefault(entry["id"], len(library_index))
        return library_index[entry["id"]]

    cases = eval_module._positive_cases(rng, _TINY_CATALOG, set(), add_to_library, 4)  # noqa: SLF001

    assert cases
    by_id = {entry["id"]: entry for entry in _TINY_CATALOG}
    for case in cases:
        assert case.draft.name.strip() != ""
        assert case.expected is not None
        source_id = next(eid for eid, fid in library_index.items() if fid == case.expected)
        original_colours = eval_module._entry_colours(by_id[source_id])  # noqa: SLF001
        assert duplicates.colour_relation(case.colours, original_colours) == "same colour"


def test_negative_colour_cases_sometimes_leave_the_colour_unset(eval_module: ModuleType) -> None:
    by_group, _ = eval_module._group_catalog(_TINY_CATALOG)  # noqa: SLF001
    siblings = eval_module._colour_siblings(by_group)  # noqa: SLF001
    saw_colourless = saw_a_real_colour = False

    for seed in range(20):
        rng = random.Random(seed)  # noqa: S311
        library_index: dict[str, int] = {}

        def add_to_library(entry: dict, library_index: dict[str, int] = library_index) -> int:
            library_index.setdefault(entry["id"], len(library_index))
            return library_index[entry["id"]]

        cases = eval_module._negative_colour_cases(rng, _TINY_CATALOG, siblings, set(), add_to_library, 2)  # noqa: SLF001
        saw_colourless = saw_colourless or any(case.colours is None for case in cases)
        saw_a_real_colour = saw_a_real_colour or any(case.colours is not None for case in cases)

    assert saw_colourless, "some drafts should leave the colour unset, the Svelte form's starting state"
    assert saw_a_real_colour, "some drafts should still carry a real, different colour"


def test_group_key_ignores_spool_weight(eval_module: ModuleType) -> None:
    same_product_smaller_spool = {"manufacturer": "Formfutura", "material": "rPET", "diameter": 1.75, "weight": 250}
    same_product_larger_spool = {"manufacturer": "Formfutura", "material": "rPET", "diameter": 1.75, "weight": 1000}

    assert eval_module._group_key(same_product_smaller_spool) == eval_module._group_key(same_product_larger_spool)  # noqa: SLF001


def test_negative_product_cases_never_add_an_excluded_entry_as_entry_a(eval_module: ModuleType) -> None:
    # Two lines with two colours each, so entries repeat quickly across attempts and an id picked
    # as entry_b (typed, excluded) is very likely to also come up as an entry_a candidate later.
    catalog = [
        {
            "id": f"creality-{material.lower()}-{colour.lower()}",
            "manufacturer": "Creality",
            "name": colour,
            "material": material,
            "diameter": 1.75,
            "weight": 1000,
            "color_hex": colour_hex,
            "color_hexes": None,
        }
        for material in ("ABS", "PLA")
        for colour, colour_hex in (("White", "FFFFFF"), ("Black", "000000"))
    ]
    _, by_manufacturer = eval_module._group_catalog(catalog)  # noqa: SLF001
    multi_line = ["Creality"]

    for seed in range(20):
        rng = random.Random(seed)  # noqa: S311
        library_index: dict[str, int] = {}
        excluded_ids: set[str] = set()

        def add_to_library(entry: dict, library_index: dict[str, int] = library_index) -> int:
            library_index.setdefault(entry["id"], len(library_index))
            return library_index[entry["id"]]

        eval_module._negative_product_cases(  # noqa: SLF001
            rng,
            by_manufacturer,
            multi_line,
            library_index,
            excluded_ids,
            add_to_library,
            10,
        )

        clash = excluded_ids & library_index.keys()
        assert not clash, f"seed {seed}: an excluded (typed) product ended up in the library too: {clash}"


def test_negatives_that_are_duplicates_detects_an_exact_tier_hit(eval_module: ModuleType) -> None:
    rows = [
        {
            "filament_id": 0,
            "vendor_id": 1,
            "vendor": "Acme",
            "name": "Red",
            "material": "PLA",
            "weight_g": 1000,
            "diameter_mm": 1.75,
            "colours": ("ff0000",),
        },
    ]
    draft = duplicates.FilamentDraft(vendor_name="Acme", name="RED", material="PLA", color_hex="ff0000", diameter=1.75)
    # Mislabelled: this is an exact-tier duplicate of the row above, not a genuine negative.
    case = eval_module.FilamentCase("negative_product", draft, ("ff0000",), None, "RED")

    bad = eval_module._negatives_that_are_duplicates(rows, [case])  # noqa: SLF001

    assert bad == ["RED"]


def test_negatives_that_are_duplicates_ignores_positive_cases(eval_module: ModuleType) -> None:
    rows = [
        {
            "filament_id": 0,
            "vendor_id": 1,
            "vendor": "Acme",
            "name": "Red",
            "material": "PLA",
            "weight_g": 1000,
            "diameter_mm": 1.75,
            "colours": ("ff0000",),
        },
    ]
    draft = duplicates.FilamentDraft(vendor_name="Acme", name="RED", material="PLA", color_hex="ff0000", diameter=1.75)
    case = eval_module.FilamentCase("positive", draft, ("ff0000",), 0, "RED")

    assert eval_module._negatives_that_are_duplicates(rows, [case]) == []  # noqa: SLF001


def test_build_filament_dataset_never_treats_a_weight_variant_as_a_negative(eval_module: ModuleType) -> None:
    # "ReForm - rPET Orange" sold in two spool sizes, plus a genuinely different Formfutura line so
    # there is still something to build a real "different product" negative from.
    catalog = [
        {
            "id": "formfutura-reform-orange-250",
            "manufacturer": "Formfutura",
            "name": "ReForm - rPET Orange",
            "material": "rPET",
            "diameter": 1.75,
            "weight": 250,
            "color_hex": "FF8800",
            "color_hexes": None,
        },
        {
            "id": "formfutura-reform-orange-1000",
            "manufacturer": "Formfutura",
            "name": "ReForm - rPET Orange",
            "material": "rPET",
            "diameter": 1.75,
            "weight": 1000,
            "color_hex": "FF8800",
            "color_hexes": None,
        },
        {
            "id": "formfutura-easyfil-white",
            "manufacturer": "Formfutura",
            "name": "EasyFil PLA White",
            "material": "PLA",
            "diameter": 1.75,
            "weight": 1000,
            "color_hex": "FFFFFF",
            "color_hexes": None,
        },
    ]

    for seed in range(6):
        # Raises AssertionError if a negative case turns out to be an exact-tier duplicate.
        eval_module._build_filament_dataset(catalog, seed=seed, count=6)  # noqa: SLF001


# --- Filaments: scoring --------------------------------------------------------------------


_FILAMENT_LIBRARY = [
    {
        "filament_id": 0,
        "vendor_id": 1,
        "vendor": "Acme",
        "name": "Red",
        "material": "PLA",
        "weight_g": 1000,
        "diameter_mm": 1.75,
        "colours": ("ff0000",),
    },
    {
        "filament_id": 1,
        "vendor_id": 1,
        "vendor": "Acme",
        "name": "Blue",
        "material": "PLA",
        "weight_g": 1000,
        "diameter_mm": 1.75,
        "colours": ("0000ff",),
    },
]


async def test_run_filament_case_uses_the_exact_tier_and_skips_the_model(eval_module: ModuleType) -> None:
    draft = duplicates.FilamentDraft(vendor_name="Acme", name="RED", material="PLA", color_hex="ff0000", diameter=1.75)
    case = eval_module.FilamentCase("positive", draft, ("ff0000",), 0, "RED")
    config = decision.DecisionConfig(base_url="https://api.typesafe.ai", model="jev-latest")

    result = await eval_module._run_filament_case(config, _FILAMENT_LIBRARY, case)  # noqa: SLF001

    assert result.exact == 0
    assert result.candidates is None
    assert result.answer is None


async def test_run_filament_case_baseline_only_never_calls_the_model(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explode(*_args: object, **_kwargs: object) -> dict:
        msg = "ask_choices must not be called with config=None"
        raise AssertionError(msg)

    monkeypatch.setattr(decision, "ask_choices", explode)

    draft = duplicates.FilamentDraft(
        vendor_name="Acme",
        name="Not In Library",
        material="PLA",
        color_hex="123456",
        diameter=1.75,
    )
    case = eval_module.FilamentCase("negative_product", draft, ("123456",), None, "Not In Library")

    result = await eval_module._run_filament_case(None, _FILAMENT_LIBRARY, case)  # noqa: SLF001

    assert result.exact is None
    assert result.candidates is None
    assert result.answer is None


async def test_run_filament_case_asks_the_model_when_there_is_no_exact_match(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = duplicates.FilamentDraft(vendor_name="Acme", name="Reed", material="PLA", color_hex="ff0000", diameter=1.75)
    case = eval_module.FilamentCase("positive", draft, ("ff0000",), 0, "Reed")
    config = decision.DecisionConfig(base_url="https://api.typesafe.ai", model="jev-latest")

    async def stub_ask(_config: object, _state: object, questions: dict) -> dict:
        assert "filament" in questions
        return {"filament": _answer("f0", 0.9)}

    monkeypatch.setattr(decision, "ask_choices", stub_ask)

    result = await eval_module._run_filament_case(config, _FILAMENT_LIBRARY, case)  # noqa: SLF001

    assert result.exact is None
    assert result.candidates is not None
    assert result.answer.choice == "f0"
    assert result.model_pick(0.6) == 0


async def test_run_filament_case_filters_out_a_different_colour_candidate(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same name, same everything but colour: the model must never even be offered the blue one.
    rows = [
        {**_FILAMENT_LIBRARY[0], "name": "Chroma"},
        {**_FILAMENT_LIBRARY[1], "name": "Chroma"},
    ]
    draft = duplicates.FilamentDraft(
        vendor_name="Acme",
        name="Acme Chroma",
        material="PLA",
        color_hex="ff0000",
        diameter=1.75,
    )
    case = eval_module.FilamentCase("positive", draft, ("ff0000",), 0, "Acme Chroma")
    config = decision.DecisionConfig(base_url="https://api.typesafe.ai", model="jev-latest")

    async def stub_ask(_config: object, _state: object, questions: dict) -> dict:
        assert set(questions["filament"]["criteria"]) == {"f0", duplicates._NONE}  # noqa: SLF001
        return {"filament": _answer("f0", 0.9)}

    monkeypatch.setattr(decision, "ask_choices", stub_ask)

    result = await eval_module._run_filament_case(config, rows, case)  # noqa: SLF001

    assert result.candidates == [duplicates.Match(id=0, name=duplicates._filament_label(rows[0]))]  # noqa: SLF001
    assert result.model_pick(0.6) == 0


async def test_run_filament_case_records_a_decision_error_without_raising(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = duplicates.FilamentDraft(vendor_name="Acme", name="Reed", material="PLA", color_hex="ff0000", diameter=1.75)
    case = eval_module.FilamentCase("positive", draft, ("ff0000",), 0, "Reed")
    config = decision.DecisionConfig(base_url="https://api.typesafe.ai", model="jev-latest")

    async def failing(*_args: object, **_kwargs: object) -> dict:
        raise decision.DecisionError("HTTP 429")

    monkeypatch.setattr(decision, "ask_choices", failing)

    result = await eval_module._run_filament_case(config, _FILAMENT_LIBRARY, case)  # noqa: SLF001

    assert result.error == "HTTP 429"
    assert result.answer is None
    assert result.model_pick(0.5) is None


def test_print_filament_report_includes_the_other_colour_rate(
    eval_module: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidates = [duplicates.Match(id=0, name="Acme Chroma (PLA)")]
    results = [
        eval_module.FilamentCaseResult("Reed", 0, "positive", 0, None, None),
        eval_module.FilamentCaseResult("Acme Chroma", None, "negative_colour", None, candidates, _answer("f0", 0.65)),
        eval_module.FilamentCaseResult("Speedy", None, "negative_product", None, None, None),
    ]

    eval_module._print_filament_report(results)  # noqa: SLF001
    out = capsys.readouterr().out

    assert "3 cases (1 duplicates, 2 not)" in out
    assert "Code tier only (exact match)" in out
    assert "Code tier plus decision model" in out
    assert "Other-colour false-warning rate (same product, a real different colour or none set yet" in out
    assert out.rstrip().endswith("100%")


# --- Filaments: CLI -------------------------------------------------------------------------


async def test_main_filaments_baseline_only_needs_no_endpoint(
    eval_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_TINY_CATALOG), encoding="utf-8")

    result = await eval_module._main_filaments(catalog_path=catalog_path, seed=1, count=4, baseline_only=True)  # noqa: SLF001

    assert result == 0
    assert "Code tier only" in capsys.readouterr().out


async def test_main_filaments_without_baseline_only_needs_an_endpoint(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(decision.ENV_BASE_URL, raising=False)
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_TINY_CATALOG), encoding="utf-8")

    result = await eval_module._main_filaments(catalog_path=catalog_path, seed=1, count=4, baseline_only=False)  # noqa: SLF001

    assert result == 2
    assert "--baseline-only" in capsys.readouterr().err


async def test_main_filaments_missing_catalog_file(
    eval_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = await eval_module._main_filaments(  # noqa: SLF001
        catalog_path=tmp_path / "missing.json",
        seed=1,
        count=4,
        baseline_only=True,
    )

    assert result == 2
    assert "not found" in capsys.readouterr().err


def test_main_requires_catalog_with_filaments(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["duplicate_eval.py", "--filaments"])

    with pytest.raises(SystemExit) as exit_info:
        eval_module.main()

    assert exit_info.value.code == 2
    assert "--catalog" in capsys.readouterr().err


def test_main_dispatches_to_filaments_with_parsed_arguments(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = ["duplicate_eval.py", "--filaments", "--catalog", "cat.json", "--seed", "3", "--count", "10"]
    monkeypatch.setattr(sys, "argv", [*argv, "--baseline-only"])
    calls = []

    async def fake_main_filaments(*, catalog_path: Path, seed: int, count: int, baseline_only: bool) -> int:
        calls.append((catalog_path, seed, count, baseline_only))
        return 0

    monkeypatch.setattr(eval_module, "_main_filaments", fake_main_filaments)

    with pytest.raises(SystemExit) as exit_info:
        eval_module.main()

    assert exit_info.value.code == 0
    assert calls == [(Path("cat.json"), 3, 10, True)]
