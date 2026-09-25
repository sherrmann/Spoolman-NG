"""Match-rerank eval (prototype, `poe match-rerank-eval`).

Scan-to-Spool's fuzzy matching (`spoolman.spoolintake.score_candidate`) picks the shortlist;
a decision model (see `spoolman.decision`) can then reorder it. This measures whether that
reordering actually helps, or just moves the right answer around without improving on the
fuzzy order — and, since the reranker never adds a "this isn't any of them" candidate to the
shortlist itself, how often it still hands a confident-looking top pick when none of the
candidates is right.

For each fixture case it builds the shortlist exactly as the product's catalog stage does --
score every candidate with `score_candidate`, drop those under the catalog cut-off, sort by
`match_percent` descending and keep the top five -- and then reranks that shortlist with
`spoolintake.rerank_matches`, in the shape `build_matches` passes. It reports
top-1 accuracy for both against each case's expected candidate, the cases where the two
orders disagree, and, for the cases where no candidate is right, how often the reranked
top candidate still gets a probability of 0.5 or more -- a false match a user could accept
without looking closely.

Cases marked `tuned_against_fuzzy` were written by trying label readings until the fuzzy
score picked the wrong candidate. They show whether reranking can recover such cases, but
they are chosen against the baseline, so they are reported separately and left out of the
headline accuracy.

Needs a live decision-model endpoint, so it is not part of CI -- run it before a release and
whenever the reranker's prompt or scoring changes:

    SPOOLMAN_AI_DECISION_BASE_URL=https://api.typesafe.ai SPOOLMAN_AI_DECISION_API_KEY=... uv run poe match-rerank-eval
"""

# ruff: noqa: T201  (this is a CLI report; print is the point)

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Run directly as `python scripts/match_rerank_eval.py` (poe's invocation, and the documented
# one) rather than as an installed package: CPython puts the *script's* directory on
# sys.path[0], not the repo root, and spoolman is not pip-installed here -- so the repo root
# has to be added by hand before the local-package import below can resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spoolman import decision, spoolintake

CASES_PATH = Path(__file__).with_name("match_rerank_eval_cases.json")

#: A reranked top candidate at or above this probability is what the review screen's
#: preselection would hand the user without them touching anything -- the bar for calling it
#: a false match on a case where none of the candidates is actually right.
_FALSE_MATCH_THRESHOLD = 0.5


@dataclass
class CaseResult:
    """How one fixture went; indexes are into the case's original `candidates` list."""

    case_id: str
    tuned: bool
    expected: int | None
    #: Whether the expected candidate made the shortlist at all (always True for null cases).
    expected_shortlisted: bool
    baseline_top1: int | None
    rerank_top1: int | None
    rerank_top1_prob: float | None
    error: str | None = None


def _score_candidates(extraction: dict, candidates: list[dict]) -> list[dict]:
    """Build the shortlist exactly as `spoolintake.match_catalog` does: cut-off, order, limit.

    Reuses `score_candidate` directly rather than reimplementing its formula, so a change to
    the scoring weights is automatically measured here too. Each entry keeps
    `_original_index` so the case's `candidates` position survives both this sort and the
    rerank that follows -- `rerank_matches` returns new dicts, but it copies every key it
    does not itself set.
    """
    scored = [
        {
            **candidate,
            "match_percent": int(
                spoolintake.score_candidate(
                    extraction,
                    vendor=candidate.get("vendor"),
                    name=candidate.get("name"),
                    material=candidate.get("material"),
                    weight_g=candidate.get("weight_g"),
                )
                * 100,
            ),
        }
        for candidate in candidates
    ]
    shortlisted = [entry for entry in scored if entry["match_percent"] >= int(spoolintake._CATALOG_MIN_SCORE * 100)]  # noqa: SLF001
    shortlisted.sort(key=lambda entry: -entry["match_percent"])
    return shortlisted[: spoolintake._MATCH_LIMIT]  # noqa: SLF001


async def _run_case(config: decision.DecisionConfig, case: dict) -> CaseResult:
    """Score one fixture; a decision-endpoint failure is recorded, not raised.

    One flaky request must not abort the rest of the eval, and a case that failed is excluded
    from the accuracy counts below rather than silently scored as wrong.
    """
    extraction = case["extraction"]
    expected = case["expected"]
    indexed = [{**candidate, "_original_index": index} for index, candidate in enumerate(case["candidates"])]
    scored = _score_candidates(extraction, indexed)
    baseline_top1 = scored[0]["_original_index"] if scored else None
    tuned = bool(case.get("tuned_against_fuzzy"))
    shortlisted = expected is None or any(entry["_original_index"] == expected for entry in scored)

    try:
        reranked = await spoolintake.rerank_matches(config, extraction, {"catalog": scored})
    except decision.DecisionError as exc:
        return CaseResult(case["id"], tuned, expected, shortlisted, baseline_top1, None, None, error=str(exc))

    catalog = reranked.get("catalog", [])
    top = catalog[0] if catalog else None
    rerank_top1 = top["_original_index"] if top else None
    rerank_top1_prob = top.get("rerank_probability") if top else None
    return CaseResult(case["id"], tuned, expected, shortlisted, baseline_top1, rerank_top1, rerank_top1_prob)


def _accuracy_line(label: str, cases: list[CaseResult]) -> float:
    """Print baseline vs reranked top-1 for one group of cases; return the reranked accuracy."""
    baseline = sum(r.baseline_top1 == r.expected for r in cases)
    reranked = sum(r.rerank_top1 == r.expected for r in cases)
    missed = sum(not r.expected_shortlisted for r in cases)
    total = len(cases)
    print(f"{label} ({total} cases, {missed} with the right answer not shortlisted by fuzzy matching):")
    print(f"  baseline (fuzzy order)  {baseline}/{total} ({baseline / total:.0%})")
    print(f"  reranked                {reranked}/{total} ({reranked / total:.0%})")
    return reranked / total


def _print_report(results: list[CaseResult]) -> float:
    """Print the headline numbers and the disagreements; return the headline reranked accuracy."""
    ok = [r for r in results if r.error is None]
    errored = [r for r in results if r.error is not None]
    headline = [r for r in ok if r.expected is not None and not r.tuned]
    tuned = [r for r in ok if r.expected is not None and r.tuned]
    null_cases = [r for r in ok if r.expected is None]

    rerank_accuracy = _accuracy_line("Top-1 accuracy", headline) if headline else 0.0
    if tuned:
        _accuracy_line("Tuned against fuzzy matching, not in the headline", tuned)
    print()

    disagreements = [r for r in ok if r.baseline_top1 != r.rerank_top1]
    if disagreements:
        print(f"Cases where baseline and reranked top-1 differ ({len(disagreements)}):")
        for r in disagreements:
            print(
                f"  {r.case_id}: expected={r.expected}  baseline={r.baseline_top1}  "
                f"reranked={r.rerank_top1} (p={r.rerank_top1_prob})",
            )
        print()

    if null_cases:
        # With nothing right on offer, the review screen still preselects the first shortlisted
        # candidate; the baseline has no probability, so any non-empty shortlist counts against it.
        baseline_false = [r for r in null_cases if r.baseline_top1 is not None]
        rerank_false = [
            r for r in null_cases if r.rerank_top1_prob is not None and r.rerank_top1_prob >= _FALSE_MATCH_THRESHOLD
        ]
        print(f"Cases with no right candidate ({len(null_cases)}):")
        print(f"  baseline preselects a wrong candidate  {len(baseline_false)}/{len(null_cases)}")
        print(
            f"  reranked top candidate at p >= {_FALSE_MATCH_THRESHOLD:.0%}  {len(rerank_false)}/{len(null_cases)}",
        )
        for r in rerank_false:
            print(f"    {r.case_id}: top candidate {r.rerank_top1} at p={r.rerank_top1_prob}")
        print()

    if errored:
        print(f"Skipped {len(errored)} case(s) after a decision-endpoint error:")
        for r in errored:
            print(f"  {r.case_id}: {r.error}")

    return rerank_accuracy


async def _main(min_accuracy: float) -> int:
    config = decision.resolve_config()
    if config is None:
        print(
            "No decision-model endpoint configured. Set SPOOLMAN_AI_DECISION_BASE_URL "
            "(and optionally SPOOLMAN_AI_DECISION_API_KEY / SPOOLMAN_AI_DECISION_MODEL).",
            file=sys.stderr,
        )
        return 2

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not cases:
        print(f"No fixture cases found in {CASES_PATH}.", file=sys.stderr)
        return 2

    results = [await _run_case(config, case) for case in cases]
    rerank_accuracy = _print_report(results)

    return 0 if rerank_accuracy >= min_accuracy else 1


def main() -> None:
    """Entry point for `poe match-rerank-eval`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-accuracy", type=float, default=0.7)
    sys.exit(asyncio.run(_main(parser.parse_args().min_accuracy)))


if __name__ == "__main__":
    main()
