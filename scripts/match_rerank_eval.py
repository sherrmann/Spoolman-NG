"""Match-rerank eval (prototype, `poe match-rerank-eval`).

Scan-to-Spool's fuzzy matching (`spoolman.spoolintake.score_candidate`) picks the shortlist;
a decision model (see `spoolman.decision`) can then reorder it. This measures whether that
reordering actually helps, or just moves the right answer around without improving on the
fuzzy order, and how often the model answers "none of these" when none of the candidates is
right (the product then keeps the fuzzy order, so the review screen still preselects the
first candidate either way).

For each fixture case it builds the shortlist exactly as the product's catalog stage does --
score every candidate with `score_candidate`, drop those under the catalog cut-off, sort by
`match_percent` descending and keep the top five -- and then reranks that shortlist with
the same code `build_matches` uses. It reports top-1 accuracy for both against each case's
expected candidate, the cases where the two orders disagree, and how often the model
answered "none". A case whose request failed makes the run fail rather than shrink the
denominator.

Cases marked `tuned_against_fuzzy` were written by trying label readings until the fuzzy
score picked the wrong candidate. They show whether reranking can recover such cases, but
they are chosen against the baseline, so they are reported separately and left out of the
headline accuracy.

Real-catalog mode (``--catalog``, ``--photos``, ``--generated``) lets the product build each
shortlist itself with spoolintake.match_catalog over a SpoolmanDB catalog, from your own photos'
extractions (ai_eval_vision.py --dump-extractions) or from generated readings
(match_eval_noise.py). It also reports how often the right product is shortlisted at all, which
bounds both orders. ``--baseline-only`` runs it without a decision endpoint. ``--flip-diameter``
simulates a misread diameter in every reading, generated or from photos. ``--dump-results FILE`` writes one JSON line
per case, for a later ``--compare OLD.jsonl NEW.jsonl`` between two code versions, with no
catalog or endpoint needed. See docs/ai.md.

Needs a live decision-model endpoint, so it is not part of CI -- run it before a release and
whenever the reranker's prompt or scoring changes:

    SPOOLMAN_AI_DECISION_BASE_URL=https://api.typesafe.ai SPOOLMAN_AI_DECISION_API_KEY=... uv run poe match-rerank-eval
"""

# ruff: noqa: T201  (this is a CLI report; print is the point)

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path

# Run directly as `python scripts/match_rerank_eval.py` (poe's invocation, and the documented
# one) rather than as an installed package: CPython puts the *script's* directory on
# sys.path[0], not the repo root, and spoolman is not pip-installed here -- so the repo root
# has to be added by hand before the local-package import below can resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Sibling modules in scripts/ (match_eval_noise) import as top-level modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from spoolman import decision, externaldb, spoolintake

CASES_PATH = Path(__file__).with_name("match_rerank_eval_cases.json")


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
    #: Whether the model answered "none of these".
    answered_none: bool = False
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

    One flaky request must not hide the other results, but it does fail the run (see _main).
    """
    extraction = case["extraction"]
    expected = case["expected"]
    indexed = [{**candidate, "_original_index": index} for index, candidate in enumerate(case["candidates"])]
    scored = _score_candidates(extraction, indexed)
    baseline_top1 = scored[0]["_original_index"] if scored else None
    tuned = bool(case.get("tuned_against_fuzzy"))
    shortlisted = expected is None or any(entry["_original_index"] == expected for entry in scored)

    try:
        reranked, answers = await spoolintake._rerank_with_answers(config, extraction, {"catalog": scored})  # noqa: SLF001
    except decision.DecisionError as exc:
        return CaseResult(case["id"], tuned, expected, shortlisted, baseline_top1, None, None, error=str(exc))

    catalog = reranked.get("catalog", [])
    top = catalog[0] if catalog else None
    rerank_top1 = top["_original_index"] if top else None
    rerank_top1_prob = top.get("rerank_probability") if top else None
    answered_none = "catalog" in answers and answers["catalog"].choice == spoolintake._RERANK_NONE  # noqa: SLF001
    return CaseResult(
        case["id"],
        tuned,
        expected,
        shortlisted,
        baseline_top1,
        rerank_top1,
        rerank_top1_prob,
        answered_none=answered_none,
    )


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
        # The product keeps the fuzzy order on a "none" answer, so the review screen preselects a
        # wrong candidate whenever the shortlist is non-empty, reranked or not. What reranking
        # adds is the model's "none", which a later UI could show as a warning.
        # A case whose shortlist is empty asks the model nothing, so it cannot answer "none".
        asked = [r for r in null_cases if r.baseline_top1 is not None]
        said_none = [r for r in asked if r.answered_none]
        print(f"Cases with no right candidate ({len(null_cases)}):")
        print(f"  a wrong candidate is preselected  {len(asked)}/{len(null_cases)}")
        print(f"  the model answered 'none'         {len(said_none)}/{len(asked)} of those")
        print()

    wrongly_none = [r for r in ok if r.expected is not None and r.expected_shortlisted and r.answered_none]
    if wrongly_none:
        print(f"Model answered 'none' although the right candidate was shortlisted ({len(wrongly_none)}):")
        for r in wrongly_none:
            print(f"  {r.case_id}")
        print()

    if errored:
        print(f"{len(errored)} case(s) failed with a decision-endpoint error:")
        for r in errored:
            print(f"  {r.case_id}: {r.error}")

    return rerank_accuracy


# --- Real-catalog mode --------------------------------------------------------------------
#
# The fixture cases above hand-pick two to five candidates. The modes below instead let the
# product build the shortlist itself, with spoolintake.match_catalog over a real SpoolmanDB
# catalog, so they measure what a scan would actually offer.


@dataclass
class CatalogCase:
    """One label reading with the catalog entry it should match (None: not in the catalog)."""

    case_id: str
    source: str
    extraction: dict
    catalog_id: str | None
    #: Noise operators applied to a generated reading (see match_eval_noise.py); empty for photos.
    noise: tuple[str, ...] = ()


@dataclass
class CatalogResult:
    """How one catalog-mode case went."""

    case: CatalogCase
    #: Whether the right product is on the fuzzy shortlist at all; reranking cannot fix a miss.
    shortlisted: bool
    #: Whether the shortlist was empty (nothing to preselect, nothing to ask the model).
    empty: bool
    baseline_ok: bool
    #: Whether fuzzy's top two candidates share a score and only one of them is right, so the
    #: catalog's file order, not the score, decided the fuzzy top-1 result.
    top_tied: bool = False
    rerank_ok: bool | None = None
    #: 1-based position of the first shortlisted candidate `same_product` accepts, or None if
    #: there is no expected candidate or none of the shortlist is it.
    right_rank: int | None = None
    answered_none: bool = False
    error: str | None = None


def _norm(value: object) -> str:
    return " ".join(str(value or "").lower().split())


def same_product(candidate: dict, expected: dict, extraction: dict) -> bool:
    """Whether a shortlisted candidate is the expected catalog entry's product.

    SpoolmanDB lists one product several times, once per diameter, spool type and spool size, and
    a label that shows none of them cannot tell them apart. So manufacturer, name, material and weight must
    match, and the diameter (the labelled row's) only when the reading has one.
    """
    if (
        _norm(candidate.get("vendor")) != _norm(expected.get("manufacturer"))
        or _norm(candidate.get("name")) != _norm(expected.get("name"))
        or _norm(candidate.get("material")) != _norm(expected.get("material"))
        or spoolintake.coerce_number(candidate.get("weight_g")) != spoolintake.coerce_number(expected.get("weight"))
    ):
        return False
    if extraction.get("diameter_mm") is None:
        return True
    # Compare with the labelled row, not with the reading: a misread diameter must not turn the
    # wrong variant into a right answer.
    return spoolintake.coerce_number(candidate.get("diameter_mm")) == spoolintake.coerce_number(
        expected.get("diameter")
    )


def load_catalog_file(path: Path | None) -> tuple[list[dict], str]:
    """Load the catalog from ``path`` (default: Spoolman's synced cache) and describe it.

    The description carries the entry count and a SHA-256, because every number this mode prints
    depends on the catalog version.
    """
    source = path or externaldb.get_filaments_file()
    try:
        raw = source.read_bytes()
    except OSError:
        return [], f"{source} (missing)"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [], f"{source} (not JSON)"
    entries = [entry for entry in parsed if isinstance(entry, dict)] if isinstance(parsed, list) else []
    return entries, f"{source}: {len(entries)} entries, sha256 {hashlib.sha256(raw).hexdigest()[:16]}"


class EvalInputError(Exception):
    """An input file for the eval is missing or malformed; the message says which and where."""


@dataclass
class PhotoSet:
    """The photo folder's readings, sorted by what can be measured."""

    cases: list[CatalogCase]
    #: Photos with an extraction but no ``catalog_id`` yet.
    unlabelled: list[CatalogCase]
    #: Photos listed in cases.json with no extraction, usually because extraction failed. They
    #: are left out of the numbers, so they must be reported: they tend to be the hardest labels.
    missing: list[str]
    #: Files listed more than once in cases.json; only the first entry counts.
    duplicates: list[str]


def _read_extractions(path: Path) -> dict[str, dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        msg = f"Cannot read the extractions file {path}: {exc.strerror or exc}."
        raise EvalInputError(msg) from exc
    dumped: dict[str, dict] = {}
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            file, extraction = record["file"], record["extraction"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            msg = f"{path}, line {number}: not a {{file, extraction}} JSON record."
            raise EvalInputError(msg) from exc
        if file in dumped:
            msg = f"{path}, line {number}: {file} appears twice; dump the extractions again."
            raise EvalInputError(msg)
        dumped[file] = extraction
    return dumped


def photo_cases(photos: Path, extractions: Path | None) -> PhotoSet:
    """Pair the photo folder's cases.json labels with extractions dumped by ai_eval_vision.py.

    A case counts once its entry in cases.json has a ``catalog_id`` key: a SpoolmanDB id, or null
    for a spool that is not in the catalog.
    """
    cases_file = photos / "cases.json"
    try:
        labels = json.loads(cases_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"Cannot read {cases_file}: {exc}."
        raise EvalInputError(msg) from exc
    dumped = _read_extractions(extractions or photos / "extractions.jsonl")
    result = PhotoSet(cases=[], unlabelled=[], missing=[], duplicates=[])
    seen: set[str] = set()
    for label in labels:
        file = label["file"]
        if file in seen:
            result.duplicates.append(file)
            continue
        seen.add(file)
        if file not in dumped:
            result.missing.append(file)
        elif "catalog_id" not in label:
            result.unlabelled.append(CatalogCase(file, "photos", dumped[file], None))
        else:
            result.cases.append(CatalogCase(file, "photos", dumped[file], label["catalog_id"]))
    return result


def generated_cases(catalog: list[dict], n: int, seed: int) -> list[CatalogCase]:
    """Label readings generated from catalog entries (see scripts/match_eval_noise.py)."""
    import match_eval_noise  # noqa: PLC0415 - a sibling script module, only needed for this mode

    return [
        CatalogCase(case["id"], "generated", case["extraction"], case["catalog_id"], tuple(case["noise"]))
        for case in match_eval_noise.generate_cases(catalog, n, seed)
    ]


def flip_diameter_reading(extraction: dict) -> dict:
    """Simulate a misread diameter (``--flip-diameter``): a 1.75 mm reading becomes 2.85, a 2.85/3 mm one 1.75.

    A missing diameter is left alone. `same_product` always checks against the labelled row's
    true diameter, not the reading, so flipping it here still leaves a flipped case judged
    against the real product rather than mistaken for a different one.
    """
    # By filament size, as the scorer sees it, so a photo reading of 1.76 or 2.88 flips too.
    size = spoolintake._diameter_class(extraction.get("diameter_mm"))  # noqa: SLF001
    if size is None:
        return extraction
    return {**extraction, "diameter_mm": 2.85 if size else 1.75}


def _raw_score(extraction: dict, candidate: dict) -> float:
    """Recompute the unrounded score match_catalog sorted by (match_percent is rounded for display)."""
    return spoolintake.score_candidate(
        extraction,
        vendor=candidate.get("vendor"),
        name=candidate.get("name"),
        material=candidate.get("material"),
        weight_g=spoolintake.coerce_number(candidate.get("weight_g")),
        diameter_mm=spoolintake.coerce_number(candidate.get("diameter_mm")),
    )


async def run_catalog_case(
    config: decision.DecisionConfig | None,
    case: CatalogCase,
    by_id: dict[str, dict],
) -> CatalogResult:
    """Shortlist one reading with the product's own catalog stage, then rerank it (unless config is None)."""
    shortlist = spoolintake.match_catalog(case.extraction)
    expected = by_id.get(case.catalog_id) if case.catalog_id is not None else None

    def ok(candidates: list[dict]) -> bool:
        if expected is None:
            return False
        return bool(candidates) and same_product(candidates[0], expected, case.extraction)

    right_rank = None
    if expected is not None:
        right_rank = next(
            (index + 1 for index, c in enumerate(shortlist) if same_product(c, expected, case.extraction)),
            None,
        )

    result = CatalogResult(
        case=case,
        shortlisted=expected is None or right_rank is not None,
        empty=not shortlist,
        baseline_ok=ok(shortlist),
        right_rank=right_rank,
        top_tied=(
            expected is not None
            and len(shortlist) > 1
            and _raw_score(case.extraction, shortlist[0]) == _raw_score(case.extraction, shortlist[1])
            and same_product(shortlist[0], expected, case.extraction)
            != same_product(shortlist[1], expected, case.extraction)
        ),
    )
    if config is None:
        return result
    try:
        reranked, answers = await spoolintake._rerank_with_answers(  # noqa: SLF001
            config,
            case.extraction,
            {"catalog": shortlist},
        )
    except decision.DecisionError as exc:
        result.error = str(exc)
        return result
    result.rerank_ok = ok(reranked["catalog"])
    result.answered_none = "catalog" in answers and answers["catalog"].choice == spoolintake._RERANK_NONE  # noqa: SLF001
    return result


def _rate(label: str, hits: int, total: int) -> None:
    print(f"  {label:<40}{hits}/{total} ({hits / total:.0%})")


def _print_matchable(matchable: list[CatalogResult]) -> None:
    total = len(matchable)
    _rate("right product on the fuzzy shortlist", sum(r.shortlisted for r in matchable), total)
    _rate("top-1, fuzzy order", sum(r.baseline_ok for r in matchable), total)
    # A tie at the top is settled by the catalog's file order, not by the score, so a rerank can
    # "fix" or "break" these cases without the fuzzy order having had an opinion.
    _rate("fuzzy top-1 decided by file order", sum(r.top_tied for r in matchable), total)
    if any(r.rerank_ok is not None for r in matchable):
        _rate("top-1, reranked", sum(bool(r.rerank_ok) for r in matchable), total)
        print(f"  {'none although it was shortlisted':<40}{sum(r.answered_none for r in matchable if r.shortlisted)}")


def _print_by_noise(matchable: list[CatalogResult]) -> None:
    """Break generated readings down by noise operator: which kinds of damage each order copes with."""
    reranked = any(r.rerank_ok is not None for r in matchable)
    operators = sorted({op for r in matchable for op in r.case.noise})
    print("  by noise operator (a case can have several):")
    for name, group in [("(none)", [r for r in matchable if not r.case.noise])] + [
        (op, [r for r in matchable if op in r.case.noise]) for op in operators
    ]:
        if not group:
            continue
        total = len(group)
        line = (
            f"    {name:<20} n={total:<4} shortlisted {sum(r.shortlisted for r in group) / total:4.0%}"
            f"  fuzzy {sum(r.baseline_ok for r in group) / total:4.0%}"
        )
        if reranked:
            line += f"  reranked {sum(bool(r.rerank_ok) for r in group) / total:4.0%}"
        print(line)


def print_catalog_report(results: list[CatalogResult]) -> None:
    """Print fuzzy vs reranked per source, the recall ceiling and the 'none' answers."""
    for source in sorted({r.case.source for r in results}):
        group = [r for r in results if r.case.source == source and r.error is None]
        matchable = [r for r in group if r.case.catalog_id is not None]
        absent = [r for r in group if r.case.catalog_id is None]
        print(f"== {source}: {len(group)} cases ({len(matchable)} in the catalog, {len(absent)} not)")
        if matchable:
            _print_matchable(matchable)
            if any(r.case.noise for r in matchable):
                _print_by_noise(matchable)
            changed = [r for r in matchable if r.rerank_ok is not None and r.rerank_ok != r.baseline_ok]
            for r in changed[:15]:
                verdict = "fixed" if r.rerank_ok else "broke"
                tied = " (fuzzy top was tied)" if r.top_tied else ""
                print(f"    {verdict}{tied}: {r.case.case_id} {json.dumps(r.case.extraction, ensure_ascii=False)}")
        if absent:
            asked = [r for r in absent if not r.empty]
            print(f"  {'not in catalog, wrong entry preselected':<40}{len(asked)}/{len(absent)}")
            if any(r.rerank_ok is not None for r in absent):
                said_none = sum(r.answered_none for r in asked)
                print(f"  {'not in catalog, model answered none':<40}{said_none}/{len(asked)}")
        print()
    errored = [r for r in results if r.error is not None]
    if errored:
        print(f"{len(errored)} case(s) failed with a decision-endpoint error:")
        for r in errored:
            print(f"  {r.case.case_id}: {r.error}")


def write_results(path: Path, results: list[CatalogResult]) -> None:
    """Write one JSON line per catalog-mode case, for a later ``--compare`` between two runs.

    Overwrites ``path``. The point is per-case before/after comparisons between two code
    versions -- run this on each, then ``--compare`` the two files -- rather than an ad-hoc script.
    """
    lines = (
        json.dumps(
            {
                "case_id": r.case.case_id,
                "source": r.case.source,
                "catalog_id": r.case.catalog_id,
                "shortlisted": r.shortlisted,
                "baseline_ok": r.baseline_ok,
                "rerank_ok": r.rerank_ok,
                "top_tied": r.top_tied,
                "right_rank": r.right_rank,
                "error": r.error,
            },
            ensure_ascii=False,
        )
        for r in results
    )
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def _top1(row: dict) -> bool:
    """Return the row's effective top-1 verdict: reranked when it ran, fuzzy order otherwise."""
    return bool(row["rerank_ok"] if row["rerank_ok"] is not None else row["baseline_ok"])


def read_dumped_results(path: Path) -> list[dict]:
    """Read a file written by ``write_results``."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        msg = f"Cannot read {path}: {exc.strerror or exc}."
        raise EvalInputError(msg) from exc
    try:
        return [json.loads(line) for line in lines if line.strip()]
    except json.JSONDecodeError as exc:
        msg = f"{path}: not a --dump-results file ({exc})."
        raise EvalInputError(msg) from exc


#: Cap on the worse-case ids listed by --compare, same as print_catalog_report's changed-cases list.
_WORSE_SHOWN = 15


def _comparable_pairs(old: list[dict], new: list[dict]) -> tuple[list[tuple[dict, dict]], list[str]]:
    """Pair cases present in both dumps; leave out any whose decision request failed in either.

    A failed rerank falls back to the fuzzy order, so comparing it against a real rerank would
    count a change that never happened, in the headline as much as case by case.
    """
    new_by_id = {row["case_id"]: row for row in new}
    pairs, errored = [], []
    for row in old:
        new_row = new_by_id.get(row["case_id"])
        if new_row is None:
            continue
        if row.get("error") or new_row.get("error"):
            errored.append(row["case_id"])
        else:
            pairs.append((row, new_row))
    return pairs, errored


def print_comparison(old: list[dict], new: list[dict]) -> None:
    """Print, per source, shortlisted and top-1 counts old vs new, and which cases flipped.

    Counts cover only the cases both dumps contain and scored without a decision-request error.
    """
    pairs, errored = _comparable_pairs(old, new)
    for source in sorted({row["source"] for row in old} | {row["source"] for row in new}):
        group = [(a, b) for a, b in pairs if a["source"] == source]
        total = len(group)
        print(f"== {source}: {total} cases compared")
        if group:
            print(
                f"  shortlisted  {sum(a['shortlisted'] for a, _ in group)}/{total} -> "
                f"{sum(b['shortlisted'] for _, b in group)}/{total}",
            )
            print(
                f"  top-1        {sum(_top1(a) for a, _ in group)}/{total} -> "
                f"{sum(_top1(b) for _, b in group)}/{total}",
            )
    better = [a["case_id"] for a, b in pairs if not _top1(a) and _top1(b)]
    worse = [a["case_id"] for a, b in pairs if _top1(a) and not _top1(b)]
    print(f"\n{len(better)} case(s) better, {len(worse)} worse")
    if errored:
        print(f"  left out, a decision request failed in one run: {', '.join(errored[:_WORSE_SHOWN])}")
    if worse:
        shown = ", ".join(worse[:_WORSE_SHOWN])
        more = f" ... {len(worse) - _WORSE_SHOWN} more" if len(worse) > _WORSE_SHOWN else ""
        print(f"  worse: {shown}{more}")


def _compare_main(old_path: Path, new_path: Path) -> int:
    try:
        old, new = read_dumped_results(old_path), read_dumped_results(new_path)
    except EvalInputError as exc:
        print(exc, file=sys.stderr)
        return 2
    print_comparison(old, new)
    return 0


def print_suggestions(cases: list[CatalogCase], catalog: list[dict], limit: int = 10) -> None:
    """For labelling photos: the closest catalog rows per reading, below the shortlist cut-off too.

    Ranked by the fuzzy score, which is what is being evaluated, so the list deliberately goes
    past the product's cut-off and top five: the right row must be findable even where fuzzy
    matching would miss it.
    """
    for case in cases:
        scored = sorted(
            (
                (
                    spoolintake.score_candidate(
                        case.extraction,
                        vendor=entry.get("manufacturer"),
                        name=entry.get("name"),
                        material=entry.get("material"),
                        weight_g=spoolintake.coerce_number(entry.get("weight")),
                        diameter_mm=spoolintake.coerce_number(entry.get("diameter")),
                    ),
                    entry,
                )
                for entry in catalog
            ),
            key=lambda pair: -pair[0],
        )
        print(f"{case.case_id}: {json.dumps(case.extraction, ensure_ascii=False)}")
        for score, entry in scored[:limit]:
            print(
                f"  {score:.2f}  {entry.get('id')}  ({entry.get('manufacturer')} / {entry.get('name')} / "
                f"{entry.get('material')} / {entry.get('weight')} g / {entry.get('diameter')} mm)",
            )
        print()


def print_find(catalog: list[dict], query: str, limit: int = 25) -> None:
    """List catalog rows whose id, manufacturer or name contains every word of ``query``.

    The fuzzy-ranked suggestions can miss the right row entirely (SpoolmanDB renames products,
    e.g. PolyTerra became "Panchroma Matte (Formerly PolyTerra)"), so labelling needs a search
    that does not depend on the score being evaluated.
    """
    words = _norm(query).split()
    hits = [
        entry
        for entry in catalog
        if all(word in _norm(f"{entry.get('id')} {entry.get('manufacturer')} {entry.get('name')}") for word in words)
    ]
    for entry in hits[:limit]:
        print(
            f"  {entry.get('id')}  ({entry.get('manufacturer')} / {entry.get('name')} / "
            f"{entry.get('material')} / {entry.get('weight')} g / {entry.get('diameter')} mm)",
        )
    if len(hits) > limit:
        print(f"  ... {len(hits) - limit} more; narrow the search")
    if not hits:
        print("  no rows match")


async def _catalog_main(args: argparse.Namespace) -> int:
    catalog, description = load_catalog_file(args.catalog)
    if not catalog:
        print(
            f"No catalog to match against ({description}). Download SpoolmanDB's filaments.json and pass it "
            "with --catalog, e.g. curl -o filaments.json https://sherrmann.github.io/SpoolmanDB/filaments.json",
            file=sys.stderr,
        )
        return 2
    print(f"Catalog: {description}\n")
    if args.find:
        print_find(catalog, args.find)
        return 0
    # Make the product's catalog stage read this catalog, so match_catalog runs unchanged.
    original_loader = spoolintake.load_catalog
    spoolintake.load_catalog = lambda: catalog
    try:
        return await _run_catalog_modes(args, catalog)
    finally:
        spoolintake.load_catalog = original_loader


def _load_photos(photos: PhotoSet, by_id: dict[str, dict]) -> list[CatalogCase]:
    """Report what the photo folder holds and return the cases that can be measured.

    Raises EvalInputError for a catalog_id this catalog does not have.
    """
    if photos.duplicates:
        print(f"Listed more than once in cases.json, first entry used: {', '.join(photos.duplicates)}\n")
    if photos.missing:
        print(
            f"{len(photos.missing)} photo(s) have no extraction (it failed or was not dumped) and are "
            f"left out of the numbers: {', '.join(photos.missing)}\n",
        )
    if photos.unlabelled:
        names = ", ".join(c.case_id for c in photos.unlabelled)
        print(f"Unlabelled photos, left out (add a catalog_id to cases.json): {names}\n")
    unknown = [c.case_id for c in photos.cases if c.catalog_id is not None and c.catalog_id not in by_id]
    if unknown:
        msg = f"catalog_id not found in this catalog: {', '.join(unknown)}"
        raise EvalInputError(msg)
    return photos.cases


def _collect_catalog_cases(args: argparse.Namespace, catalog: list[dict], by_id: dict[str, dict]) -> list[CatalogCase]:
    """Gather this run's cases from --photos and/or --generated, applying --flip-diameter."""
    cases: list[CatalogCase] = []
    if args.photos:
        photos = photo_cases(args.photos, args.extractions)
        if args.suggest:
            print_suggestions(photos.unlabelled + photos.cases, catalog)
            return []
        cases += _load_photos(photos, by_id)
    if args.generated:
        cases += generated_cases(catalog, args.generated, args.seed)
    if args.flip_diameter:
        cases = [replace(case, extraction=flip_diameter_reading(case.extraction)) for case in cases]
    return cases


async def _run_catalog_modes(args: argparse.Namespace, catalog: list[dict]) -> int:
    by_id = {entry.get("id"): entry for entry in catalog}
    try:
        cases = _collect_catalog_cases(args, catalog, by_id)
    except EvalInputError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.suggest:
        return 0
    if not cases:
        print("No cases to run.", file=sys.stderr)
        return 2

    config = None
    if not args.baseline_only:
        config = decision.resolve_config()
        if config is None:
            print(_NO_ENDPOINT, file=sys.stderr)
            return 2
    results = [await run_catalog_case(config, case, by_id) for case in cases]
    print_catalog_report(results)
    if args.dump_results:
        write_results(args.dump_results, results)
    if any(r.error is not None for r in results):
        print("\nFAIL: some cases could not be scored; rerun once the endpoint answers them all.")
        return 1
    return 0


_NO_ENDPOINT = (
    "No decision-model endpoint configured. Set SPOOLMAN_AI_DECISION_BASE_URL "
    "(and optionally SPOOLMAN_AI_DECISION_API_KEY / SPOOLMAN_AI_DECISION_MODEL), "
    "or pass --baseline-only for the fuzzy numbers alone."
)


async def _main(min_accuracy: float) -> int:
    config = decision.resolve_config()
    if config is None:
        print(_NO_ENDPOINT, file=sys.stderr)
        return 2

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not cases:
        print(f"No fixture cases found in {CASES_PATH}.", file=sys.stderr)
        return 2

    results = [await _run_case(config, case) for case in cases]
    rerank_accuracy = _print_report(results)

    if any(r.error is not None for r in results):
        print("\nFAIL: some cases could not be scored; rerun once the endpoint answers them all.")
        return 1
    return 0 if rerank_accuracy >= min_accuracy else 1


def main() -> None:
    """Entry point for `poe match-rerank-eval`."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-accuracy", type=float, help="fixture mode: fail below this (default 0.7)")
    real = parser.add_argument_group("real-catalog mode (shortlists built by the product from SpoolmanDB)")
    real.add_argument("--catalog", type=Path, help="SpoolmanDB filaments.json (default: Spoolman's synced copy)")
    real.add_argument("--photos", type=Path, help="photo folder with cases.json (entries carry catalog_id)")
    real.add_argument("--extractions", type=Path, help="JSONL from ai_eval_vision.py --dump-extractions")
    real.add_argument("--suggest", action="store_true", help="list the closest catalog rows per photo, to label")
    real.add_argument("--find", metavar="TEXT", help="search catalog rows by id, maker and name, to label")
    real.add_argument("--generated", type=int, default=0, metavar="N", help="also run N generated label readings")
    real.add_argument("--seed", type=int, default=1, help="seed for --generated")
    real.add_argument("--baseline-only", action="store_true", help="fuzzy numbers only; no decision endpoint")
    real.add_argument(
        "--flip-diameter",
        action="store_true",
        help="simulate a misread diameter in generated (and, if given too, photo) readings",
    )
    real.add_argument(
        "--dump-results",
        type=Path,
        metavar="FILE",
        help="write one JSON line per case to FILE, for a later --compare",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("OLD.jsonl", "NEW.jsonl"),
        help="compare two --dump-results files (no catalog or endpoint needed) and exit",
    )
    args = parser.parse_args()
    if args.compare:
        other = [
            name
            for name, value in (
                ("--catalog", args.catalog),
                ("--photos", args.photos),
                ("--generated", args.generated),
                ("--find", args.find),
                ("--dump-results", args.dump_results),
                ("--extractions", args.extractions),
                ("--min-accuracy", args.min_accuracy is not None),
                ("--seed", args.seed != 1),
                ("--suggest", args.suggest),
                ("--flip-diameter", args.flip_diameter),
                ("--baseline-only", args.baseline_only),
            )
            if value
        ]
        if other:
            parser.error(f"--compare stands alone; it needs no catalog or endpoint (drop {', '.join(other)})")
        sys.exit(_compare_main(Path(args.compare[0]), Path(args.compare[1])))
    if args.suggest and not args.photos:
        parser.error("--suggest lists catalog rows for photos; it needs --photos")
    if args.suggest and args.generated:
        parser.error("--suggest only labels photos; run --generated separately")
    if args.extractions and not args.photos:
        parser.error("--extractions belongs to --photos")
    if args.seed != 1 and not args.generated:
        parser.error("--seed only applies to --generated")
    if args.min_accuracy is not None and (args.photos or args.generated or args.catalog or args.find):
        parser.error("--min-accuracy only applies to the fixture cases, not to real-catalog mode")
    if args.photos or args.generated or args.catalog or args.find:
        sys.exit(asyncio.run(_catalog_main(args)))
    sys.exit(asyncio.run(_main(0.7 if args.min_accuracy is None else args.min_accuracy)))


if __name__ == "__main__":
    main()
