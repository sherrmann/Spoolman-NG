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

    cases, unlabelled = eval_module.photo_cases(tmp_path, None)

    by_file = {case.case_id: case for case in cases}
    assert by_file["a.jpg"].catalog_id == "acme-pla"
    assert "b.jpg" in by_file
    assert by_file["b.jpg"].catalog_id is None
    assert "d.jpg" not in by_file, "no dumped extraction: left out entirely"
    assert [case.case_id for case in unlabelled] == ["c.jpg"]


def test_photo_cases_extractions_argument_overrides_the_default_path(eval_module: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "cases.json").write_text(json.dumps([{"file": "a.jpg", "catalog_id": "acme-pla"}]), encoding="utf-8")
    # Deliberately wrong, to prove it is not read when --extractions is given.
    (tmp_path / "extractions.jsonl").write_text("not even json\n", encoding="utf-8")
    override = tmp_path / "other.jsonl"
    override.write_text(json.dumps({"file": "a.jpg", "extraction": {"vendor": "Acme"}}) + "\n", encoding="utf-8")

    cases, unlabelled = eval_module.photo_cases(tmp_path, override)

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
    assert "right product on the fuzzy shortlist  3/3 (100%)" in out
    assert "top-1, fuzzy order                    2/3 (67%)" in out
    assert "top-1, reranked                       2/3 (67%)" in out
    assert "not in catalog, wrong entry preselected  1/2" in out
    assert "not in catalog, model answered 'none'    1/1" in out
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


async def test_catalog_main_restores_load_catalog_on_error(eval_module: ModuleType, tmp_path: Path) -> None:
    catalog_path = tmp_path / "filaments.json"
    catalog_path.write_text(json.dumps(_CATALOG), encoding="utf-8")
    original = eval_module.spoolintake.load_catalog
    # No cases.json in this folder, so photo_cases blows up mid-run.
    args = _catalog_args(catalog=catalog_path, photos=tmp_path / "missing", baseline_only=True)

    with pytest.raises(FileNotFoundError):
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
