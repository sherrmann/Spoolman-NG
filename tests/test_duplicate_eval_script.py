"""Scoring and CLI logic of scripts/duplicate_eval.py (`poe duplicate-eval`).

The eval needs a live decision endpoint for the model tier, so it is out of CI; these tests feed
its scoring logic hand-made results and a stubbed endpoint instead.
"""

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from spoolman import decision, duplicates

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "duplicate_eval.py"


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
