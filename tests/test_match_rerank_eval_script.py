"""Report logic of scripts/match_rerank_eval.py (`poe match-rerank-eval`).

The eval needs a live decision endpoint, so it is out of CI; these tests feed its report and
exit-code logic hand-made results and a stubbed endpoint instead.
"""

import argparse
import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from spoolman import decision

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "match_rerank_eval.py"

#: A tiny SpoolmanDB-shaped catalog, reused across the real-catalog-mode tests below.
_CATALOG = [
    {"id": "acme-pla", "manufacturer": "Acme", "name": "Pro PLA", "material": "PLA", "weight": 1000, "diameter": 1.75},
    {
        "id": "other-petg",
        "manufacturer": "Other Co",
        "name": "Basic PETG",
        "material": "PETG",
        "weight": 1000,
        "diameter": 1.75,
    },
]


@pytest.fixture
def eval_module() -> Iterator[ModuleType]:
    """Import the script by path (it is a standalone script, not an installed package)."""
    spec = importlib.util.spec_from_file_location("_match_rerank_eval_under_test", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("_match_rerank_eval_under_test", None)


def _result(module: ModuleType, case_id: str, **fields: object) -> object:
    defaults = {
        "tuned": False,
        "expected": 0,
        "expected_shortlisted": True,
        "baseline_top1": 0,
        "rerank_top1": 0,
        "rerank_top1_prob": 0.9,
    }
    return module.CaseResult(case_id, **{**defaults, **fields})


def test_report_counts_none_answers_only_where_the_model_was_asked(
    eval_module: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = [
        _result(eval_module, "right"),
        _result(eval_module, "tuned", tuned=True, expected=1, baseline_top1=0, rerank_top1=1),
        _result(eval_module, "none-asked", expected=None, answered_none=True),
        _result(eval_module, "none-empty", expected=None, baseline_top1=None, rerank_top1=None),
        _result(eval_module, "wrongly-none", answered_none=True),
    ]

    accuracy = eval_module._print_report(results)  # noqa: SLF001
    out = capsys.readouterr().out

    assert accuracy == 1.0, "tuned cases stay out of the headline"
    assert "a wrong candidate is preselected  1/2" in out
    assert "the model answered 'none'         1/1 of those" in out
    assert "wrongly-none" in out


async def test_main_fails_when_a_case_errors(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(decision.ENV_BASE_URL, "https://api.typesafe.ai")

    async def failing(*_args: object, **_kwargs: object) -> dict:
        raise decision.DecisionError("HTTP 429")

    monkeypatch.setattr(decision, "ask_choices", failing)

    assert await eval_module._main(0.0) == 1  # noqa: SLF001
    assert "failed with a decision-endpoint error" in capsys.readouterr().out


# --- same_product -------------------------------------------------------------------------


def test_same_product_matches_ignoring_case_and_extra_spaces(eval_module: ModuleType) -> None:
    candidate = {"vendor": "  ACME ", "name": "Pro   PLA", "material": "pla", "weight_g": 1000}
    expected = {"manufacturer": "Acme", "name": "Pro PLA", "material": "PLA", "weight": 1000}
    assert eval_module.same_product(candidate, expected, {}) is True


def test_same_product_rejects_a_different_weight(eval_module: ModuleType) -> None:
    candidate = {"vendor": "Acme", "name": "Pro PLA", "material": "PLA", "weight_g": 500}
    expected = {"manufacturer": "Acme", "name": "Pro PLA", "material": "PLA", "weight": 1000}
    assert eval_module.same_product(candidate, expected, {}) is False


def test_same_product_diameter_only_checked_when_the_extraction_has_one(eval_module: ModuleType) -> None:
    candidate = {"vendor": "Acme", "name": "Pro PLA", "material": "PLA", "weight_g": 1000, "diameter_mm": 2.85}
    expected = {"manufacturer": "Acme", "name": "Pro PLA", "material": "PLA", "weight": 1000, "diameter": 1.75}

    assert eval_module.same_product(candidate, expected, {}) is True, "no diameter_mm in the reading: ignored"
    assert eval_module.same_product(candidate, expected, {"diameter_mm": 1.75}) is False, "given and mismatched"


def test_same_product_compares_diameter_with_the_labelled_row_not_the_reading(eval_module: ModuleType) -> None:
    """A misread diameter must not make the wrong variant count as right."""
    wrong_variant = {"vendor": "Acme", "name": "Pro PLA", "material": "PLA", "weight_g": 1000, "diameter_mm": 2.85}
    right_variant = {**wrong_variant, "diameter_mm": 1.75}
    labelled = {"manufacturer": "Acme", "name": "Pro PLA", "material": "PLA", "weight": 1000, "diameter": 1.75}
    misread = {"diameter_mm": 2.85}

    assert eval_module.same_product(wrong_variant, labelled, misread) is False
    assert eval_module.same_product(right_variant, labelled, misread) is True


# --- load_catalog_file ---------------------------------------------------------------------


def test_load_catalog_file_valid(eval_module: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "filaments.json"
    path.write_text(json.dumps(_CATALOG), encoding="utf-8")

    entries, description = eval_module.load_catalog_file(path)

    assert entries == _CATALOG
    assert f"{len(_CATALOG)} entries" in description
    assert "sha256" in description


def test_load_catalog_file_missing(eval_module: ModuleType, tmp_path: Path) -> None:
    entries, description = eval_module.load_catalog_file(tmp_path / "nope.json")

    assert entries == []
    assert description.endswith("(missing)")


def test_load_catalog_file_not_json(eval_module: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")

    entries, description = eval_module.load_catalog_file(path)

    assert entries == []
    assert description.endswith("(not JSON)")


# --- photo_cases ---------------------------------------------------------------------------


def test_photo_cases_labels_and_skips(eval_module: ModuleType, tmp_path: Path) -> None:
    cases_json = [
        {"file": "a.jpg", "catalog_id": "acme-pla"},
        {"file": "b.jpg", "catalog_id": None},
        {"file": "c.jpg"},  # unlabelled: no catalog_id key at all
        {"file": "d.jpg", "catalog_id": "other-petg"},  # never dumped: skipped
    ]
    (tmp_path / "cases.json").write_text(json.dumps(cases_json), encoding="utf-8")
    dumped = [
        {"file": "a.jpg", "extraction": {"vendor": "Acme"}},
        {"file": "b.jpg", "extraction": {"vendor": "Other"}},
        {"file": "c.jpg", "extraction": {"vendor": "X"}},
    ]
    (tmp_path / "extractions.jsonl").write_text(
        "\n".join(json.dumps(record) for record in dumped),
        encoding="utf-8",
    )

    photos = eval_module.photo_cases(tmp_path, None)
    cases, unlabelled = photos.cases, photos.unlabelled

    by_file = {case.case_id: case for case in cases}
    assert by_file["a.jpg"].catalog_id == "acme-pla"
    assert "b.jpg" in by_file
    assert by_file["b.jpg"].catalog_id is None
    assert "d.jpg" not in by_file, "no dumped extraction: left out entirely"
    assert [case.case_id for case in unlabelled] == ["c.jpg"]
    assert photos.missing == ["d.jpg"], "labelled but not dumped: reported, not silently dropped"


def test_photo_cases_extractions_argument_overrides_the_default_path(eval_module: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "cases.json").write_text(json.dumps([{"file": "a.jpg", "catalog_id": "acme-pla"}]), encoding="utf-8")
    # Deliberately wrong, to prove it is not read when --extractions is given.
    (tmp_path / "extractions.jsonl").write_text("not even json\n", encoding="utf-8")
    override = tmp_path / "other.jsonl"
    override.write_text(json.dumps({"file": "a.jpg", "extraction": {"vendor": "Acme"}}) + "\n", encoding="utf-8")

    photos = eval_module.photo_cases(tmp_path, override)
    cases, unlabelled = photos.cases, photos.unlabelled

    assert unlabelled == []
    assert len(cases) == 1
    assert cases[0].extraction == {"vendor": "Acme"}


# --- run_catalog_case -----------------------------------------------------------------------


async def test_run_catalog_case_baseline_ok_when_expected_is_fuzzys_top(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_module.spoolintake, "load_catalog", lambda: _CATALOG)
    by_id = {entry["id"]: entry for entry in _CATALOG}
    extraction = {"vendor": "Acme", "name": "Pro PLA", "material": "PLA", "weight_g": 1000}
    case = eval_module.CatalogCase("case-1", "test", extraction, "acme-pla")

    result = await eval_module.run_catalog_case(None, case, by_id)

    assert result.shortlisted is True
    assert result.baseline_ok is True
    assert result.rerank_ok is None, "config=None: no rerank attempted"


async def test_run_catalog_case_shortlisted_false_below_the_cut_off(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = [
        {
            "id": "unrelated",
            "manufacturer": "Bizarro",
            "name": "Zzz Totally Unrelated",
            "material": "ABS",
            "weight": 9999,
            "diameter": 3.0,
        },
    ]
    monkeypatch.setattr(eval_module.spoolintake, "load_catalog", lambda: catalog)
    by_id = {entry["id"]: entry for entry in catalog}
    extraction = {"vendor": "Acme", "name": "Pro PLA", "material": "PLA", "weight_g": 1000}
    case = eval_module.CatalogCase("case-1", "test", extraction, "unrelated")

    result = await eval_module.run_catalog_case(None, case, by_id)

    assert result.shortlisted is False
    assert result.baseline_ok is False


#: Two products the fuzzy scorer ranks the "wrong" one first: its name is an exact match, while
#: "right" (the expected one) only wins on vendor once you ignore the fuzzy score.
_RERANK_CATALOG = [
    {"id": "wrong", "manufacturer": "Acme", "name": "Pro PLA X", "material": "PLA", "weight": 1000, "diameter": 1.75},
    {"id": "right", "manufacturer": "Xyzcorp", "name": "Pro PLA", "material": "PLA", "weight": 1000, "diameter": 1.75},
]
_RERANK_EXTRACTION = {"vendor": "Acme", "name": "Pro PLA", "material": "PLA", "weight_g": 1000}


def _choice_answer(choice: str) -> decision.ChoiceAnswer:
    return decision.ChoiceAnswer(choice=choice, probabilities={}, confidence=None)


async def test_run_catalog_case_rerank_ok_follows_a_stubbed_answer(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_module.spoolintake, "load_catalog", lambda: _RERANK_CATALOG)
    by_id = {entry["id"]: entry for entry in _RERANK_CATALOG}
    case = eval_module.CatalogCase("case-1", "test", _RERANK_EXTRACTION, "right")
    config = decision.DecisionConfig(base_url="https://api.typesafe.ai", model="jev-latest")

    async def answer_c2(*_args: object, **_kwargs: object) -> dict:
        return {"catalog": _choice_answer("c2")}

    monkeypatch.setattr(decision, "ask_choices", answer_c2)

    result = await eval_module.run_catalog_case(config, case, by_id)

    assert result.baseline_ok is False, "fuzzy order puts the wrong product first"
    assert result.rerank_ok is True, "the stub promoted the expected (second) candidate"
    assert result.answered_none is False
    assert result.error is None


async def test_run_catalog_case_answered_none(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_module.spoolintake, "load_catalog", lambda: _RERANK_CATALOG)
    by_id = {entry["id"]: entry for entry in _RERANK_CATALOG}
    case = eval_module.CatalogCase("case-1", "test", _RERANK_EXTRACTION, "right")
    config = decision.DecisionConfig(base_url="https://api.typesafe.ai", model="jev-latest")

    async def answer_none(*_args: object, **_kwargs: object) -> dict:
        return {"catalog": _choice_answer(eval_module.spoolintake._RERANK_NONE)}  # noqa: SLF001

    monkeypatch.setattr(decision, "ask_choices", answer_none)

    result = await eval_module.run_catalog_case(config, case, by_id)

    assert result.answered_none is True
    assert result.error is None


async def test_run_catalog_case_decision_error_sets_error(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_module.spoolintake, "load_catalog", lambda: _RERANK_CATALOG)
    by_id = {entry["id"]: entry for entry in _RERANK_CATALOG}
    case = eval_module.CatalogCase("case-1", "test", _RERANK_EXTRACTION, "right")
    config = decision.DecisionConfig(base_url="https://api.typesafe.ai", model="jev-latest")

    async def failing(*_args: object, **_kwargs: object) -> dict:
        raise decision.DecisionError("HTTP 429")

    monkeypatch.setattr(decision, "ask_choices", failing)

    result = await eval_module.run_catalog_case(config, case, by_id)

    assert result.error == "HTTP 429"
    assert result.rerank_ok is None


# --- print_catalog_report -------------------------------------------------------------------


def test_print_catalog_report(eval_module: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    case_cls, result_cls = eval_module.CatalogCase, eval_module.CatalogResult
    results = [
        result_cls(
            case=case_cls("p1", "photos", {"v": 1}, "id1"),
            shortlisted=True,
            empty=False,
            baseline_ok=True,
            rerank_ok=True,
        ),
        result_cls(
            case=case_cls("p2", "photos", {"v": 2}, "id2"),
            shortlisted=True,
            empty=False,
            baseline_ok=False,
            rerank_ok=True,
        ),
        result_cls(
            case=case_cls("p3", "photos", {"v": 3}, "id3"),
            shortlisted=True,
            empty=False,
            baseline_ok=True,
            rerank_ok=False,
        ),
        result_cls(
            case=case_cls("p4", "photos", {"v": 4}, None),
            shortlisted=True,
            empty=False,
            baseline_ok=False,
            rerank_ok=False,
            answered_none=True,
        ),
        result_cls(case=case_cls("p5", "photos", {"v": 5}, None), shortlisted=True, empty=True, baseline_ok=False),
        result_cls(
            case=case_cls("g1", "generated", {"v": 6}, "id6"),
            shortlisted=False,
            empty=True,
            baseline_ok=False,
            error="boom",
        ),
    ]

    eval_module.print_catalog_report(results)
    out = capsys.readouterr().out

    assert "== photos: 5 cases (3 in the catalog, 2 not)" in out
    flat = " ".join(out.split())
    assert "right product on the fuzzy shortlist 3/3 (100%)" in flat
    assert "top-1, fuzzy order 2/3 (67%)" in flat
    assert "top-1, reranked 2/3 (67%)" in flat
    assert "not in catalog, wrong entry preselected 1/2" in flat
    assert "not in catalog, model answered none 1/1" in flat
    assert "fixed: p2" in out
    assert "broke: p3" in out
    assert "== generated: 0 cases (0 in the catalog, 0 not)" in out, "the errored case is excluded from the group"
    assert "1 case(s) failed with a decision-endpoint error" in out
    assert "g1: boom" in out


# --- _catalog_main ---------------------------------------------------------------------------


def _catalog_args(**overrides: object) -> argparse.Namespace:
    defaults = {
        "min_accuracy": 0.7,
        "catalog": None,
        "photos": None,
        "extractions": None,
        "suggest": False,
        "find": None,
        "generated": 0,
        "seed": 1,
        "baseline_only": False,
        "flip_diameter": False,
        "dump_results": None,
    }
    return argparse.Namespace(**{**defaults, **overrides})


def _write_photo_case(photos: Path, catalog_id: object = "acme-pla", *, labelled: bool = True) -> None:
    photos.mkdir(exist_ok=True)
    label: dict = {"file": "a.jpg"}
    if labelled:
        label["catalog_id"] = catalog_id
    (photos / "cases.json").write_text(json.dumps([label]), encoding="utf-8")
    extraction = {"vendor": "Acme", "name": "Pro PLA", "material": "PLA", "weight_g": 1000}
    (photos / "extractions.jsonl").write_text(
        json.dumps({"file": "a.jpg", "extraction": extraction}) + "\n", encoding="utf-8"
    )


async def test_catalog_main_baseline_only_with_photos(
    eval_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_CATALOG), encoding="utf-8")
    photos = tmp_path / "photos"
    _write_photo_case(photos)
    args = _catalog_args(catalog=catalog_path, photos=photos, baseline_only=True)

    result = await eval_module._catalog_main(args)  # noqa: SLF001

    assert result == 0
    out = capsys.readouterr().out
    assert "== photos:" in out
    assert "top-1, fuzzy order" in out


async def test_catalog_main_restores_load_catalog(eval_module: ModuleType, tmp_path: Path) -> None:
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_CATALOG), encoding="utf-8")
    photos = tmp_path / "photos"
    _write_photo_case(photos)
    original = eval_module.spoolintake.load_catalog
    args = _catalog_args(catalog=catalog_path, photos=photos, baseline_only=True)

    result = await eval_module._catalog_main(args)  # noqa: SLF001

    assert result == 0
    assert eval_module.spoolintake.load_catalog is original


async def test_catalog_main_restores_load_catalog_on_error(
    eval_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_CATALOG), encoding="utf-8")
    original = eval_module.spoolintake.load_catalog

    def explode(*_args: object) -> list:
        raise RuntimeError("boom")

    monkeypatch.setattr(eval_module, "generated_cases", explode)
    args = _catalog_args(catalog=catalog_path, generated=3, baseline_only=True)

    with pytest.raises(RuntimeError):
        await eval_module._catalog_main(args)  # noqa: SLF001

    assert eval_module.spoolintake.load_catalog is original


async def test_catalog_main_unknown_catalog_id(
    eval_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_CATALOG), encoding="utf-8")
    photos = tmp_path / "photos"
    _write_photo_case(photos, catalog_id="does-not-exist")
    args = _catalog_args(catalog=catalog_path, photos=photos, baseline_only=True)

    result = await eval_module._catalog_main(args)  # noqa: SLF001

    assert result == 2
    assert "catalog_id not found" in capsys.readouterr().err


async def test_catalog_main_missing_catalog(
    eval_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _catalog_args(catalog=tmp_path / "nope.json", photos=tmp_path, baseline_only=True)

    result = await eval_module._catalog_main(args)  # noqa: SLF001

    assert result == 2
    err = capsys.readouterr().err
    assert "Download SpoolmanDB" in err
    assert "--catalog" in err


async def test_catalog_main_find(eval_module: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_CATALOG), encoding="utf-8")

    found = await eval_module._catalog_main(_catalog_args(catalog=catalog_path, find="acme"))  # noqa: SLF001
    assert found == 0
    assert "acme-pla" in capsys.readouterr().out

    empty = await eval_module._catalog_main(_catalog_args(catalog=catalog_path, find="nonexistent-brand-zzz"))  # noqa: SLF001
    assert empty == 0
    assert "no rows match" in capsys.readouterr().out


async def test_catalog_main_suggest_lists_rows_below_the_cut_off(
    eval_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog = [
        {
            "id": "unrelated",
            "manufacturer": "Bizarro",
            "name": "Zzz Totally Unrelated",
            "material": "ABS",
            "weight": 9999,
            "diameter": 3.0,
        },
    ]
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    photos = tmp_path / "photos"
    _write_photo_case(photos, labelled=False)
    args = _catalog_args(catalog=catalog_path, photos=photos, suggest=True, baseline_only=True)

    result = await eval_module._catalog_main(args)  # noqa: SLF001

    assert result == 0
    out = capsys.readouterr().out
    assert "unrelated" in out
    extraction = {"vendor": "Acme", "name": "Pro PLA", "material": "PLA", "weight_g": 1000}
    score = eval_module.spoolintake.score_candidate(
        extraction,
        vendor=catalog[0]["manufacturer"],
        name=catalog[0]["name"],
        material=catalog[0]["material"],
        weight_g=catalog[0]["weight"],
    )
    assert score < 0.5, "the row must be below the shortlist cut-off for this to test --suggest's point"


async def test_catalog_main_without_baseline_only_needs_endpoint(
    eval_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(decision.ENV_BASE_URL, raising=False)
    monkeypatch.delenv(decision.ENV_API_KEY, raising=False)
    monkeypatch.delenv(decision.ENV_MODEL, raising=False)
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_CATALOG), encoding="utf-8")
    photos = tmp_path / "photos"
    _write_photo_case(photos)
    args = _catalog_args(catalog=catalog_path, photos=photos)

    result = await eval_module._catalog_main(args)  # noqa: SLF001

    assert result == 2
    assert "--baseline-only" in capsys.readouterr().err


# --- review fixes: missing, duplicate and malformed inputs; ties; noise breakdown --------------


def _write_photos(folder: Path, labels: list[dict], dump_lines: list[str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cases.json").write_text(json.dumps(labels), encoding="utf-8")
    (folder / "extractions.jsonl").write_text("\n".join(dump_lines), encoding="utf-8")
    return folder


def test_photo_cases_keeps_the_first_of_duplicate_files(eval_module: ModuleType, tmp_path: Path) -> None:
    folder = _write_photos(
        tmp_path / "p",
        [{"file": "a.jpg", "catalog_id": "acme-pla"}, {"file": "a.jpg", "catalog_id": "other-petg"}],
        [json.dumps({"file": "a.jpg", "extraction": {"vendor": "Acme"}})],
    )

    photos = eval_module.photo_cases(folder, None)

    assert [c.catalog_id for c in photos.cases] == ["acme-pla"]
    assert photos.duplicates == ["a.jpg"]


@pytest.mark.parametrize(
    ("dump_lines", "message"),
    [
        (["garbage"], "line 1"),
        ([json.dumps({"file": "a.jpg"})], "line 1"),
        ([json.dumps({"file": "a.jpg", "extraction": {}}), json.dumps({"file": "a.jpg", "extraction": {}})], "twice"),
    ],
)
def test_photo_cases_rejects_a_malformed_dump(
    eval_module: ModuleType,
    tmp_path: Path,
    dump_lines: list[str],
    message: str,
) -> None:
    folder = _write_photos(tmp_path / "p", [{"file": "a.jpg", "catalog_id": "acme-pla"}], dump_lines)

    with pytest.raises(eval_module.EvalInputError, match=message):
        eval_module.photo_cases(folder, None)


async def test_catalog_main_reports_bad_inputs_with_exit_2(
    eval_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_CATALOG), encoding="utf-8")
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "cases.json").write_text(json.dumps([{"file": "a.jpg", "catalog_id": "acme-pla"}]), encoding="utf-8")

    result = await eval_module._catalog_main(  # noqa: SLF001
        _catalog_args(catalog=catalog_path, photos=folder, baseline_only=True),
    )

    assert result == 2
    assert "extractions.jsonl" in capsys.readouterr().err


async def test_catalog_main_lists_photos_without_an_extraction(
    eval_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_CATALOG), encoding="utf-8")
    folder = _write_photos(
        tmp_path / "p",
        [{"file": "a.jpg", "catalog_id": "acme-pla"}, {"file": "failed.jpg", "catalog_id": "other-petg"}],
        [json.dumps({"file": "a.jpg", "extraction": {"vendor": "Acme", "name": "Pro PLA", "material": "PLA"}})],
    )

    result = await eval_module._catalog_main(  # noqa: SLF001
        _catalog_args(catalog=catalog_path, photos=folder, baseline_only=True),
    )

    out = capsys.readouterr().out
    assert result == 0
    assert "1 photo(s) have no extraction" in out
    assert "failed.jpg" in out
    assert "== photos: 1 cases" in out


async def test_run_catalog_case_flags_a_tied_top_score(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twins = [
        {"id": "a1", "manufacturer": "Acme", "name": "Black", "material": "PLA", "weight": 1000, "diameter": 1.75},
        {"id": "b1", "manufacturer": "Bolt", "name": "Black", "material": "PLA", "weight": 1000, "diameter": 1.75},
    ]
    monkeypatch.setattr(eval_module.spoolintake, "load_catalog", lambda: twins)
    case = eval_module.CatalogCase("t", "generated", {"name": "Black", "material": "PLA", "weight_g": 1000}, "b1")

    result = await eval_module.run_catalog_case(None, case, {e["id"]: e for e in twins})

    assert result.top_tied is True
    assert result.shortlisted is True
    assert result.baseline_ok is False, "file order put Acme first"


def test_report_breaks_generated_results_down_by_noise(
    eval_module: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def result(case_id: str, noise: tuple[str, ...], *, ok: bool) -> object:
        case = eval_module.CatalogCase(case_id, "generated", {}, "x", noise)
        return eval_module.CatalogResult(case=case, shortlisted=True, empty=False, baseline_ok=ok)

    eval_module.print_catalog_report(
        [result("g1", (), ok=True), result("g2", ("drop_vendor",), ok=False), result("g3", ("drop_vendor",), ok=True)],
    )

    flat = " ".join(capsys.readouterr().out.split())
    assert "by noise operator" in flat
    assert "(none) n=1 shortlisted 100% fuzzy 100%" in flat
    assert "drop_vendor n=2 shortlisted 100% fuzzy 50%" in flat


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--catalog", "c.json", "--suggest"], "needs --photos"),
        (["--photos", "p", "--suggest", "--generated", "2"], "run --generated separately"),
        (["--catalog", "c.json", "--extractions", "e.jsonl"], "belongs to --photos"),
        (["--catalog", "c.json", "--seed", "7"], "only applies to --generated"),
        (["--generated", "5", "--min-accuracy", "0.5"], "only applies to the fixture cases"),
    ],
)
def test_main_rejects_suggest_misuse(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    message: str,
) -> None:
    monkeypatch.setattr(sys, "argv", ["match_rerank_eval.py", *argv])

    with pytest.raises(SystemExit) as exit_info:
        eval_module.main()

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


# --- flip_diameter_reading ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("diameter_mm", "expected"),
    [
        (1.75, 2.85),
        (2.85, 1.75),
        (3.0, 1.75),
        (None, None),
    ],
)
def test_flip_diameter_reading(eval_module: ModuleType, diameter_mm: float | None, expected: float | None) -> None:
    extraction = {"vendor": "Acme", "diameter_mm": diameter_mm}

    flipped = eval_module.flip_diameter_reading(extraction)

    assert flipped["diameter_mm"] == expected
    assert flipped["vendor"] == "Acme", "other fields are untouched"


def test_flip_diameter_reading_leaves_the_original_dict_alone(eval_module: ModuleType) -> None:
    extraction = {"diameter_mm": 1.75}

    eval_module.flip_diameter_reading(extraction)

    assert extraction == {"diameter_mm": 1.75}


def test_flip_diameter_still_judged_against_the_labelled_row(eval_module: ModuleType) -> None:
    """A flipped generated reading must still be scored against the true (unflipped) product."""
    labelled = {"manufacturer": "Acme", "name": "Pro PLA", "material": "PLA", "weight": 1000, "diameter": 1.75}
    candidate = {"vendor": "Acme", "name": "Pro PLA", "material": "PLA", "weight_g": 1000, "diameter_mm": 1.75}
    reading = {"diameter_mm": 1.75}

    flipped_reading = eval_module.flip_diameter_reading(reading)

    assert flipped_reading["diameter_mm"] == 2.85
    assert eval_module.same_product(candidate, labelled, flipped_reading) is True, (
        "the flipped reading is still judged against the labelled row, not against itself"
    )


async def test_collect_catalog_cases_flips_generated_and_photo_diameters(
    eval_module: ModuleType,
    tmp_path: Path,
) -> None:
    photos = tmp_path / "photos"
    _write_photo_case(photos)  # a.jpg's extraction has no diameter_mm at all
    args = _catalog_args(photos=photos, generated=2, seed=1, flip_diameter=True)

    cases = eval_module._collect_catalog_cases(args, _CATALOG, {e["id"]: e for e in _CATALOG})  # noqa: SLF001

    generated = [c for c in cases if c.source == "generated"]
    assert generated, "the tiny catalog must still yield generated cases"
    for case in generated:
        original_diameter = case.extraction.get("diameter_mm")
        assert original_diameter in (None, 2.85, 1.75), "flipped away from the catalog's raw 1.75/2.85"
    photo_case = next(c for c in cases if c.source == "photos")
    assert photo_case.extraction.get("diameter_mm") is None, "no diameter to flip: left alone"


async def test_collect_catalog_cases_without_flip_diameter_keeps_original_readings(
    eval_module: ModuleType,
) -> None:
    args = _catalog_args(generated=2, seed=1, flip_diameter=False)

    with_flip = eval_module._collect_catalog_cases(  # noqa: SLF001
        _catalog_args(generated=2, seed=1, flip_diameter=True),
        _CATALOG,
        {e["id"]: e for e in _CATALOG},
    )
    without_flip = eval_module._collect_catalog_cases(args, _CATALOG, {e["id"]: e for e in _CATALOG})  # noqa: SLF001

    assert [c.extraction.get("diameter_mm") for c in without_flip] == [1.75, 1.75]
    assert [c.extraction.get("diameter_mm") for c in with_flip] == [2.85, 2.85]


async def test_catalog_main_flip_diameter_end_to_end(
    eval_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_CATALOG), encoding="utf-8")
    args = _catalog_args(catalog=catalog_path, generated=2, baseline_only=True, flip_diameter=True)

    result = await eval_module._catalog_main(args)  # noqa: SLF001

    assert result == 0
    assert "== generated: 2 cases" in capsys.readouterr().out


# --- dump-results / --compare -----------------------------------------------------------------


def test_write_and_read_dumped_results_round_trip(eval_module: ModuleType, tmp_path: Path) -> None:
    case_cls, result_cls = eval_module.CatalogCase, eval_module.CatalogResult
    results = [
        result_cls(
            case=case_cls("p1", "photos", {}, "id1"),
            shortlisted=True,
            empty=False,
            baseline_ok=True,
            rerank_ok=True,
            top_tied=False,
            right_rank=1,
        ),
        result_cls(
            case=case_cls("p2", "photos", {}, "id2"),
            shortlisted=False,
            empty=True,
            baseline_ok=False,
            rerank_ok=None,
            top_tied=False,
            right_rank=None,
        ),
    ]
    out_path = tmp_path / "dump.jsonl"

    eval_module.write_results(out_path, results)
    rows = eval_module.read_dumped_results(out_path)

    assert rows == [
        {
            "case_id": "p1",
            "source": "photos",
            "catalog_id": "id1",
            "shortlisted": True,
            "baseline_ok": True,
            "rerank_ok": True,
            "top_tied": False,
            "right_rank": 1,
        },
        {
            "case_id": "p2",
            "source": "photos",
            "catalog_id": "id2",
            "shortlisted": False,
            "baseline_ok": False,
            "rerank_ok": None,
            "top_tied": False,
            "right_rank": None,
        },
    ]


def test_write_results_overwrites_the_file(eval_module: ModuleType, tmp_path: Path) -> None:
    out_path = tmp_path / "dump.jsonl"
    out_path.write_text("stale content that must not survive\n", encoding="utf-8")
    case_cls, result_cls = eval_module.CatalogCase, eval_module.CatalogResult
    results = [result_cls(case=case_cls("p1", "photos", {}, "id1"), shortlisted=True, empty=False, baseline_ok=True)]

    eval_module.write_results(out_path, results)

    rows = eval_module.read_dumped_results(out_path)
    assert [row["case_id"] for row in rows] == ["p1"]


async def test_run_catalog_case_right_rank_is_the_first_accepted_position(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_module.spoolintake, "load_catalog", lambda: _RERANK_CATALOG)
    by_id = {entry["id"]: entry for entry in _RERANK_CATALOG}
    case = eval_module.CatalogCase("case-1", "test", _RERANK_EXTRACTION, "right")

    result = await eval_module.run_catalog_case(None, case, by_id)

    assert result.right_rank == 2, "'right' scores below 'wrong' on fuzzy but is still shortlisted second"


async def test_run_catalog_case_right_rank_none_when_not_shortlisted(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = [
        {
            "id": "unrelated",
            "manufacturer": "Bizarro",
            "name": "Zzz Totally Unrelated",
            "material": "ABS",
            "weight": 9999,
            "diameter": 3.0,
        },
    ]
    monkeypatch.setattr(eval_module.spoolintake, "load_catalog", lambda: catalog)
    by_id = {entry["id"]: entry for entry in catalog}
    extraction = {"vendor": "Acme", "name": "Pro PLA", "material": "PLA", "weight_g": 1000}
    case = eval_module.CatalogCase("case-1", "test", extraction, "unrelated")

    result = await eval_module.run_catalog_case(None, case, by_id)

    assert result.right_rank is None


def test_print_comparison(eval_module: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    def row(case_id: str, source: str, *, shortlisted: bool, baseline_ok: bool, rerank_ok: bool | None) -> dict:
        return {
            "case_id": case_id,
            "source": source,
            "catalog_id": "id",
            "shortlisted": shortlisted,
            "baseline_ok": baseline_ok,
            "rerank_ok": rerank_ok,
            "top_tied": False,
            "right_rank": 1 if shortlisted else None,
        }

    old = [
        row("g1", "generated", shortlisted=True, baseline_ok=True, rerank_ok=None),
        row("g2", "generated", shortlisted=True, baseline_ok=False, rerank_ok=None),
        row("g3", "generated", shortlisted=False, baseline_ok=False, rerank_ok=None),
    ]
    new = [
        row("g1", "generated", shortlisted=True, baseline_ok=True, rerank_ok=None),
        row("g2", "generated", shortlisted=True, baseline_ok=True, rerank_ok=None),  # fixed
        row("g3", "generated", shortlisted=False, baseline_ok=False, rerank_ok=None),
    ]

    eval_module.print_comparison(old, new)
    flat = " ".join(capsys.readouterr().out.split())

    assert "== generated: 3 cases old, 3 new" in flat
    assert "shortlisted 2/3 -> 2/3" in flat
    assert "top-1 1/3 -> 2/3" in flat
    assert "1 case(s) better, 0 worse" in flat


def test_print_comparison_lists_worse_cases_capped_at_15(
    eval_module: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def row(case_id: str, *, ok: bool) -> dict:
        return {
            "case_id": case_id,
            "source": "generated",
            "catalog_id": "id",
            "shortlisted": True,
            "baseline_ok": ok,
            "rerank_ok": None,
            "top_tied": False,
            "right_rank": 1,
        }

    ids = [f"g{i}" for i in range(20)]
    old = [row(case_id, ok=True) for case_id in ids]
    new = [row(case_id, ok=False) for case_id in ids]

    eval_module.print_comparison(old, new)
    out = capsys.readouterr().out

    assert "20 case(s) better, 20 worse" not in out
    assert "0 case(s) better, 20 worse" in out
    assert "g19" not in out.split("worse:")[1].split("more")[0], "capped at 15 shown"
    assert "5 more" in out


def test_compare_main_reports_a_bad_file(
    eval_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n", encoding="utf-8")
    good = tmp_path / "good.jsonl"
    good.write_text("", encoding="utf-8")

    result = eval_module._compare_main(bad, good)  # noqa: SLF001

    assert result == 2
    assert "not a --dump-results file" in capsys.readouterr().err


def test_main_compare_mode_runs_without_a_catalog_or_endpoint(
    eval_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = tmp_path / "old.jsonl"
    new = tmp_path / "new.jsonl"
    row = {
        "case_id": "g1",
        "source": "generated",
        "catalog_id": "id",
        "shortlisted": True,
        "baseline_ok": True,
        "rerank_ok": None,
        "top_tied": False,
        "right_rank": 1,
    }
    old.write_text(json.dumps(row) + "\n", encoding="utf-8")
    new.write_text(json.dumps(row) + "\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["match_rerank_eval.py", "--compare", str(old), str(new)])

    with pytest.raises(SystemExit) as exit_info:
        eval_module.main()

    assert exit_info.value.code == 0
    assert "== generated" in capsys.readouterr().out


def test_main_compare_rejects_being_combined_with_catalog_mode(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["match_rerank_eval.py", "--compare", "a.jsonl", "b.jsonl", "--generated", "5"])

    with pytest.raises(SystemExit) as exit_info:
        eval_module.main()

    assert exit_info.value.code == 2
    assert "--compare stands alone" in capsys.readouterr().err


async def test_a_tie_between_variants_of_the_right_product_is_not_counted(
    eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two diameters of the same product tie, but file order cannot change the result."""
    variants = [
        {"id": "a175", "manufacturer": "Acme", "name": "Black", "material": "PLA", "weight": 1000, "diameter": 1.75},
        {"id": "a285", "manufacturer": "Acme", "name": "Black", "material": "PLA", "weight": 1000, "diameter": 2.85},
    ]
    monkeypatch.setattr(eval_module.spoolintake, "load_catalog", lambda: variants)
    reading = {"vendor": "Acme", "name": "Black", "material": "PLA", "weight_g": 1000}
    case = eval_module.CatalogCase("v", "generated", reading, "a285")

    result = await eval_module.run_catalog_case(None, case, {e["id"]: e for e in variants})

    assert result.baseline_ok is True
    assert result.top_tied is False
