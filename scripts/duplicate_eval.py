"""Duplicate-vendor eval (prototype, `poe duplicate-eval`).

The vendor duplicate check (`spoolman.duplicates`) has two tiers: an always-on exact match done
in code, and an opt-in decision-model question for the same brand written differently. The
model's suggestion is only shown once its probability for the pick reaches
`duplicates.SUGGEST_MIN_PROBABILITY` -- a wrong "did you mean" is worse than none. This measures
whether that threshold, and the tier split itself, are worth trusting: precision, recall and a
false-warning rate (a warning on a case that is *not* a duplicate) for the code tier alone, and
for code-plus-model at probability thresholds 0.5/0.6/0.7/0.8/0.9, so the threshold can be chosen
with real numbers instead of a guess.

For each fixture case (`scripts/fixtures/duplicate_vendor_cases.json`: a typed name, an existing
vendor list, and the expected duplicate's name or null) it runs the same logic
`duplicates.similar_vendor` does, without a database:

* build a `duplicates.Match` per existing vendor (synthetic ids);
* the code tier is `duplicates._exact_vendor`;
* when that finds nothing, the model tier shortlists with `duplicates._shortlist`, builds the
  question with `duplicates._vendor_question`, and answers it with `decision.ask_choices` --
  once per case, since the answer's probability does not depend on the threshold being scored.

Needs a live decision-model endpoint for the model tier, so it is not part of CI -- run it before
a release and whenever the duplicate-check prompt changes:

    SPOOLMAN_AI_DECISION_BASE_URL=https://api.typesafe.ai SPOOLMAN_AI_DECISION_API_KEY=... uv run poe duplicate-eval

``--baseline-only`` runs the code tier alone, with no endpoint needed:

    uv run poe duplicate-eval -- --baseline-only

A case whose decision request fails makes the run fail rather than shrink the denominator.
"""

# ruff: noqa: T201  (this is a CLI report; print is the point)

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Run directly as `python scripts/duplicate_eval.py` (poe's invocation, and the documented one)
# rather than as an installed package: CPython puts the *script's* directory on sys.path[0], not
# the repo root, and spoolman is not pip-installed here -- so the repo root has to be added by
# hand before the local-package import below can resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spoolman import decision, duplicates

CASES_PATH = Path(__file__).parent / "fixtures" / "duplicate_vendor_cases.json"

#: Thresholds the model tier is scored at, in addition to the shipped SUGGEST_MIN_PROBABILITY.
_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)


@dataclass
class CaseResult:
    """How one fixture case went, with everything the report needs to score it at any threshold."""

    typed: str
    expected: str | None
    #: The code tier's pick, or None; also the model tier's pick when this is not None, since
    #: `similar_vendor` never asks the model once the exact tier already found something.
    exact: str | None
    #: The shortlisted candidates the model was asked about; None when the model was not asked
    #: (an exact match already answered, or `--baseline-only`).
    candidates: list[duplicates.Match] | None
    #: The model's raw answer; None when it was not asked, or the request failed.
    answer: decision.ChoiceAnswer | None
    error: str | None = None

    def model_pick(self, threshold: float) -> str | None:
        """Return the code-plus-model tier's suggestion at ``threshold``, or None."""
        if self.exact is not None:
            return self.exact
        if self.answer is None or self.answer.choice == duplicates._NONE:  # noqa: SLF001
            return None
        probability = self.answer.probabilities.get(self.answer.choice, self.answer.confidence)
        if probability is None or probability < threshold:
            return None
        picked = next(c for c in (self.candidates or []) if f"v{c.id}" == self.answer.choice)
        return picked.name


def _vendors(existing: list[str]) -> list[duplicates.Match]:
    return [duplicates.Match(id=index, name=name) for index, name in enumerate(existing)]


async def _run_case(config: decision.DecisionConfig | None, case: dict) -> CaseResult:
    """Score one fixture case; a decision-endpoint failure is recorded, not raised.

    One flaky request must not hide the other results, but it does fail the run (see _main).
    """
    typed, expected = case["typed"], case["expected"]
    vendors = _vendors(case["existing"])
    exact = duplicates._exact_vendor(typed, vendors)  # noqa: SLF001
    exact_name = exact.name if exact is not None else None
    if exact is not None or config is None:
        return CaseResult(typed, expected, exact_name, None, None)

    candidates = duplicates._shortlist(typed, vendors)  # noqa: SLF001
    question = duplicates._vendor_question(candidates)  # noqa: SLF001
    try:
        answer = (await decision.ask_choices(config, typed, {"vendor": question}))["vendor"]
    except decision.DecisionError as exc:
        return CaseResult(typed, expected, None, candidates, None, error=str(exc))
    return CaseResult(typed, expected, None, candidates, answer)


@dataclass
class _Scores:
    """Precision, recall and false-warning rate for one tier at one threshold."""

    precision: float | None
    recall: float | None
    false_warning_rate: float | None
    wrong: list[str]


def _score(results: list[CaseResult], pick: "callable[[CaseResult], str | None]") -> _Scores:
    positives = [r for r in results if r.expected is not None]
    negatives = [r for r in results if r.expected is None]
    tp = sum(1 for r in positives if pick(r) == r.expected)
    warned = [r for r in results if pick(r) is not None]
    fp = sum(1 for r in warned if pick(r) != r.expected)
    false_warnings = sum(1 for r in negatives if pick(r) is not None)
    wrong = [r.typed for r in results if pick(r) != r.expected]
    return _Scores(
        precision=tp / (tp + fp) if (tp + fp) else None,
        recall=tp / len(positives) if positives else None,
        false_warning_rate=false_warnings / len(negatives) if negatives else None,
        wrong=wrong,
    )


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _print_scores(label: str, scores: _Scores) -> None:
    print(
        f"{label}: precision {_fmt(scores.precision)}  recall {_fmt(scores.recall)}  "
        f"false-warning rate {_fmt(scores.false_warning_rate)}",
    )
    if scores.wrong:
        print(f"  wrong: {', '.join(scores.wrong)}")


def _print_report(results: list[CaseResult]) -> None:
    positives = sum(1 for r in results if r.expected is not None)
    negatives = len(results) - positives
    print(f"{len(results)} cases ({positives} duplicates, {negatives} not)\n")

    _print_scores("Code tier only (exact match)", _score(results, lambda r: r.exact))
    print()
    if any(r.candidates is not None for r in results):  # the model was asked at least once
        print("Code tier plus decision model, by probability threshold:")
        for threshold in _THRESHOLDS:
            _print_scores(f"  threshold {threshold:.1f}", _score(results, lambda r, t=threshold: r.model_pick(t)))
        print()
        _print_scores(
            f"  shipped threshold ({duplicates.SUGGEST_MIN_PROBABILITY:.1f})",
            _score(results, lambda r: r.model_pick(duplicates.SUGGEST_MIN_PROBABILITY)),
        )


_NO_ENDPOINT = (
    "No decision-model endpoint configured. Set SPOOLMAN_AI_DECISION_BASE_URL "
    "(and optionally SPOOLMAN_AI_DECISION_API_KEY / SPOOLMAN_AI_DECISION_MODEL), "
    "or pass --baseline-only for the code-tier numbers alone."
)


async def _main(*, baseline_only: bool) -> int:
    config = None
    if not baseline_only:
        config = decision.resolve_env_config()
        if config is None:
            print(_NO_ENDPOINT, file=sys.stderr)
            return 2

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not cases:
        print(f"No fixture cases found in {CASES_PATH}.", file=sys.stderr)
        return 2

    results = [await _run_case(config, case) for case in cases]
    _print_report(results)

    errored = [r for r in results if r.error is not None]
    if errored:
        print(f"\n{len(errored)} case(s) failed with a decision-endpoint error:")
        for r in errored:
            print(f"  {r.typed}: {r.error}")
        print("\nFAIL: some cases could not be scored; rerun once the endpoint answers them all.")
        return 1
    return 0


def main() -> None:
    """Entry point for `poe duplicate-eval`."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline-only", action="store_true", help="code tier only; no decision endpoint needed")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(baseline_only=args.baseline_only)))


if __name__ == "__main__":
    main()
