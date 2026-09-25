"""Report logic of scripts/match_rerank_eval.py (`poe match-rerank-eval`).

The eval needs a live decision endpoint, so it is out of CI; these tests feed its report and
exit-code logic hand-made results and a stubbed endpoint instead.
"""

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from spoolman import decision

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "match_rerank_eval.py"


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
