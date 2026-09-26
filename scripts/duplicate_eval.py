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
import random
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Run directly as `python scripts/duplicate_eval.py` (poe's invocation, and the documented one)
# rather than as an installed package: CPython puts the *script's* directory on sys.path[0], not
# the repo root, and spoolman is not pip-installed here -- so the repo root has to be added by
# hand before the local-package import below can resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spoolman import decision, duplicates, spoolintake
from spoolman import math as colour_math

CASES_PATH = Path(__file__).parent / "fixtures" / "duplicate_vendor_cases.json"

#: Thresholds the model tier is scored at, in addition to the shipped SUGGEST_MIN_PROBABILITY.
_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)

#: Default number of filament cases `--filaments` generates when `--count` is not given.
DEFAULT_FILAMENT_COUNT = 200


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


# --- Filaments -----------------------------------------------------------------------------
#
# `--filaments --catalog PATH` builds its own cases from a SpoolmanDB `filaments.json` (one row
# per manufacturer colour, e.g. {"manufacturer": "3D-Fuel", "name": "Almond", "material": "PLA+",
# "diameter": 1.75, "weight": 1000.0, "color_hex": "CFBCAE", "color_hexes": null, ...}) rather than
# a fixture file, so the mix of cases is regenerated (deterministically, from `--seed`) each run
# instead of going stale as the catalogue changes. It exercises `duplicates.similar_filament`'s
# two tiers the same way the vendor cases exercise `similar_vendor`: `_exact_filament` for the
# code tier, then `spoolintake._rank_library` and `_filament_question` for the model tier.


@dataclass
class FilamentCase:
    """One generated filament case.

    A draft to check, and the library row it should (or should not) be reported as a duplicate of.
    """

    kind: str  # "positive", "negative_colour" or "negative_product"
    draft: duplicates.FilamentDraft
    colours: tuple[str, ...] | None
    expected: int | None
    typed: str


@dataclass
class FilamentCaseResult:
    """How one generated filament case went; mirrors `CaseResult` for the filament tier."""

    typed: str
    expected: int | None
    kind: str
    #: The code tier's pick (a library filament_id), or None; also the model tier's pick when
    #: this is not None, since `similar_filament` never asks the model once the exact tier answers.
    exact: int | None
    #: The candidates the model was asked about; None when it was not asked (an exact match
    #: already answered, or `--baseline-only`); an empty list when colour ruled every one out.
    candidates: list[duplicates.Match] | None
    answer: decision.ChoiceAnswer | None
    error: str | None = None

    def model_pick(self, threshold: float) -> int | None:
        """Return the code-plus-model tier's suggestion (a filament_id) at ``threshold``, or None."""
        if self.exact is not None:
            return self.exact
        if self.answer is None or self.answer.choice == duplicates._NONE:  # noqa: SLF001
            return None
        probability = self.answer.probabilities.get(self.answer.choice, self.answer.confidence)
        if probability is None or probability < threshold:
            return None
        picked = next(c for c in (self.candidates or []) if f"f{c.id}" == self.answer.choice)
        return picked.id


def _entry_colours(entry: dict) -> tuple[str, ...] | None:
    hexes = entry.get("color_hexes")
    multi = ",".join(hexes) if hexes else None
    return duplicates._colours(entry.get("color_hex"), multi)  # noqa: SLF001


def _group_key(entry: dict) -> tuple:
    """Return the product line an entry belongs to: same manufacturer, material and nominal size.

    Not spool weight: the backend's own duplicate check never looks at it (`_same_vendor` and
    `_same_size` in `spoolman.duplicates` do not compare weight), so two rows differing only in
    the size sold are the same product -- a genuine duplicate, not a different colour or line.
    """
    return (entry["manufacturer"], entry["material"], entry.get("diameter"))


def _draft_colour_fields(colours: tuple[str, ...] | None) -> tuple[str | None, str | None]:
    """Return the (color_hex, multi_color_hexes) pair `FilamentDraft` expects for ``colours``."""
    if not colours:
        return None, None
    if len(colours) == 1:
        return colours[0], None
    return None, ",".join(colours)


#: The CIE94 distance a positive case's colour jitter must stay under: imperceptible, per the
#: module docstring's "smallest difference people notice" note.
_JITTER_MAX_DELTA_E = 1.0


def _jitter_hex(rng: random.Random, hex_code: str) -> str:
    """Return a colour within `_JITTER_MAX_DELTA_E` of ``hex_code``.

    Or ``hex_code`` itself if ten small random nudges all overshoot that (only possible for a hex
    right at the gamut's edge).
    """
    rgb = colour_math.hex_to_rgb(hex_code)
    lab = colour_math.rgb_to_lab(rgb)
    for _ in range(10):
        nudged = [max(0, min(255, channel + rng.randint(-2, 2))) for channel in rgb]
        if colour_math.delta_e(lab, colour_math.rgb_to_lab(nudged)) < _JITTER_MAX_DELTA_E:
            return "".join(f"{channel:02x}" for channel in nudged)
    return hex_code


def _noisy_name(rng: random.Random, name: str, material: str, vendor: str) -> str:
    """Add realistic noise to a product name.

    Case, punctuation, a material word, word order, or a vendor-name prefix. Never returns an
    empty string, so a generated positive case always keeps a name for the exact tier to key on.
    """

    def case_noise(value: str) -> str:
        return rng.choice([value.upper(), value.lower(), value.title()])

    def punctuation_noise(value: str) -> str:
        return rng.choice([value.replace(" ", "-"), value.replace(" ", ""), f"{value}!", f"{value}."])

    def material_noise(value: str) -> str:
        return rng.choice([f"{value} {material}", f"{material} {value}"]) if material else value

    def order_noise(value: str) -> str:
        words = value.split()
        if len(words) < 2:  # noqa: PLR2004
            return value
        rng.shuffle(words)
        return " ".join(words)

    def vendor_noise(value: str) -> str:
        return f"{vendor} {value}" if vendor else value

    transforms = [case_noise, punctuation_noise, material_noise, order_noise, vendor_noise]
    rng.shuffle(transforms)
    result = name
    for transform in transforms[: rng.randint(1, 3)]:
        result = transform(result)
    return result or name  # belt and braces: keep the case generator's "always has a name" promise


def _group_catalog(catalog: list[dict]) -> tuple[dict[tuple, list[dict]], dict[str, list[dict]]]:
    """Group catalogue entries by product line (see `_group_key`) and by manufacturer."""
    by_group: dict[tuple, list[dict]] = defaultdict(list)
    by_manufacturer: dict[str, list[dict]] = defaultdict(list)
    for entry in catalog:
        by_group[_group_key(entry)].append(entry)
        by_manufacturer[entry["manufacturer"]].append(entry)
    return by_group, by_manufacturer


def _colour_siblings(by_group: dict[tuple, list[dict]]) -> dict[str, list[dict]]:
    """Map each entry's id to its same-line siblings of a genuinely different colour, if any.

    These are real "different colour, same product" pairs to build the key false-warning case
    from, rather than invented ones.
    """
    siblings: dict[str, list[dict]] = {}
    for group in by_group.values():
        colours_by_id = {entry["id"]: _entry_colours(entry) for entry in group}
        for entry in group:
            others = [
                other
                for other in group
                if other is not entry
                and duplicates.colour_relation(colours_by_id[entry["id"]], colours_by_id[other["id"]])
                == "different colour"
            ]
            if others:
                siblings[entry["id"]] = others
    return siblings


def _negative_product_cases(
    rng: random.Random,
    by_manufacturer: dict[str, list[dict]],
    multi_line_manufacturers: list[str],
    library_index: dict[str, int],
    excluded_ids: set[str],
    add_to_library: Callable[[dict], int],
    target: int,
) -> list[FilamentCase]:
    """Build "different product, same manufacturer" negatives.

    Adds each case's other product to the library, and keeps its typed product -- and every other
    spool weight of that same product (`_group_key` does not distinguish them) -- out of it
    (`excluded_ids`), so a weight variant can never later slip into the library and quietly turn
    this "different product" negative into a real duplicate.
    """
    cases: list[FilamentCase] = []
    attempts = 0
    while len(cases) < target and multi_line_manufacturers and attempts < target * 10:
        attempts += 1
        manufacturer = rng.choice(multi_line_manufacturers)
        # dict.fromkeys, not a set: a set's iteration order depends on PYTHONHASHSEED, which would
        # make the "same seed, same cases" promise only hold within one process.
        lines = list(dict.fromkeys(_group_key(e) for e in by_manufacturer[manufacturer]))
        rng.shuffle(lines)
        line_a, line_b = lines[0], lines[1]
        line_a_entries = [e for e in by_manufacturer[manufacturer] if _group_key(e) == line_a]
        line_b_entries = [e for e in by_manufacturer[manufacturer] if _group_key(e) == line_b]
        if any(e["id"] in excluded_ids for e in line_a_entries) or any(
            e["id"] in library_index for e in line_b_entries
        ):
            # line_a: an earlier case already promised this whole product is missing from the
            # library -- adding any spool weight of it now would undo that. line_b: some spool
            # weight of it is in the library elsewhere, so typing another is no longer a fair
            # "missing product" case.
            continue
        add_to_library(rng.choice(line_a_entries))
        entry_b = rng.choice(line_b_entries)
        excluded_ids.update(e["id"] for e in line_b_entries)  # every spool weight of it stays out
        colours = _entry_colours(entry_b)
        color_hex, multi_color_hexes = _draft_colour_fields(colours)
        draft = duplicates.FilamentDraft(
            vendor_name=entry_b["manufacturer"],
            name=entry_b["name"],
            material=entry_b["material"],
            color_hex=color_hex,
            multi_color_hexes=multi_color_hexes,
            diameter=entry_b.get("diameter"),
        )
        cases.append(FilamentCase("negative_product", draft, colours, None, draft.name or ""))
    return cases


def _positive_cases(
    rng: random.Random,
    catalog: list[dict],
    excluded_ids: set[str],
    add_to_library: Callable[[dict], int],
    target: int,
) -> list[FilamentCase]:
    """Build "same product, noisy name" positives; adds each one's product to the library."""
    pool = [e for e in catalog if e["id"] not in excluded_ids]
    rng.shuffle(pool)
    cases = []
    for entry in pool[:target]:
        filament_id = add_to_library(entry)
        colours = _entry_colours(entry)
        jittered = colours
        if colours and rng.random() < 0.5:  # noqa: PLR2004 -- half get a tiny jitter, half stay identical
            jittered = tuple(_jitter_hex(rng, colour) for colour in colours)
        color_hex, multi_color_hexes = _draft_colour_fields(jittered)
        draft = duplicates.FilamentDraft(
            vendor_name=entry["manufacturer"],
            name=_noisy_name(rng, entry["name"], entry["material"], entry["manufacturer"]),
            material=entry["material"],
            color_hex=color_hex,
            multi_color_hexes=multi_color_hexes,
            diameter=entry.get("diameter"),
        )
        cases.append(FilamentCase("positive", draft, jittered, filament_id, draft.name or ""))
    return cases


#: Share of "other colour" negatives that leave the colour unset, rather than giving a real
#: different colour: the Svelte form's starting state, before the swatch is picked.
_COLOURLESS_DRAFT_PROBABILITY = 0.5


def _negative_colour_cases(
    rng: random.Random,
    catalog: list[dict],
    colour_siblings: dict[str, list[dict]],
    excluded_ids: set[str],
    add_to_library: Callable[[dict], int],
    target: int,
) -> list[FilamentCase]:
    """Build "same product, another colour" negatives; adds each one's product to the library.

    Half (`_COLOURLESS_DRAFT_PROBABILITY`) give the draft a genuinely different real colour, taken
    from a same-line sibling; the other half leave the colour unset altogether, so the model tier
    sees "colour unknown" rather than "different colour" and must judge by name alone -- the form's
    starting state, and a harder version of the same false-warning risk.
    """
    pool = [e for e in catalog if e["id"] not in excluded_ids and e["id"] in colour_siblings]
    rng.shuffle(pool)
    cases = []
    for entry in pool[:target]:
        add_to_library(entry)  # the library must hold it: it is the "other colour" being warned about
        colours = None
        if rng.random() >= _COLOURLESS_DRAFT_PROBABILITY:
            colours = _entry_colours(rng.choice(colour_siblings[entry["id"]]))
        color_hex, multi_color_hexes = _draft_colour_fields(colours)
        draft = duplicates.FilamentDraft(
            vendor_name=entry["manufacturer"],
            name=_noisy_name(rng, entry["name"], entry["material"], entry["manufacturer"]),
            material=entry["material"],
            color_hex=color_hex,
            multi_color_hexes=multi_color_hexes,
            diameter=entry.get("diameter"),
        )
        cases.append(FilamentCase("negative_colour", draft, colours, None, draft.name or ""))
    return cases


def _negatives_that_are_duplicates(rows: list[dict], cases: list[FilamentCase]) -> list[str]:
    """Return the typed labels of "negative" cases the exact tier would itself flag as duplicates.

    A hit here is a case-generation bug, not a finding about the tool being evaluated: the eval
    invented a "not a duplicate" case that is secretly a real duplicate of its own library row.
    """
    return [
        case.typed
        for case in cases
        if case.expected is None and duplicates._exact_filament(case.draft, case.colours, rows) is not None  # noqa: SLF001
    ]


def _build_filament_dataset(catalog: list[dict], *, seed: int, count: int) -> tuple[list[dict], list[FilamentCase]]:
    """Build a library of catalogue rows and a mix of positive/negative cases against it.

    Deterministic for a given ``seed``: the same seed always builds the same library and cases,
    in the same order.
    """
    rng = random.Random(seed)  # noqa: S311 -- reproducible synthetic-eval-data generation, not security
    vendor_ids = {name: index for index, name in enumerate(sorted({e["manufacturer"] for e in catalog}))}
    by_group, by_manufacturer = _group_catalog(catalog)
    colour_siblings = _colour_siblings(by_group)
    multi_line_manufacturers = [
        name for name, entries in by_manufacturer.items() if len({_group_key(e) for e in entries}) > 1
    ]

    library_index: dict[str, int] = {}
    excluded_ids: set[str] = set()  # a "different product" negative's draft: kept out of the library

    def add_to_library(entry: dict) -> int:
        if entry["id"] not in library_index:
            library_index[entry["id"]] = len(library_index)
        return library_index[entry["id"]]

    n_positive = count // 2
    n_negative_colour = count // 4
    n_negative_product = count - n_positive - n_negative_colour

    # Built first so the positive/negative-colour picks below can avoid its excluded entries.
    cases = _negative_product_cases(
        rng,
        by_manufacturer,
        multi_line_manufacturers,
        library_index,
        excluded_ids,
        add_to_library,
        n_negative_product,
    )
    cases += _positive_cases(rng, catalog, excluded_ids, add_to_library, n_positive)
    cases += _negative_colour_cases(rng, catalog, colour_siblings, excluded_ids, add_to_library, n_negative_colour)

    # Pad the library with unrelated rows so the shortlist and ranking see a realistic library
    # size rather than just the handful of rows the cases above needed.
    target_size = max(len(library_index), min(len(catalog), count * 2))
    pool = [e for e in catalog if e["id"] not in library_index and e["id"] not in excluded_ids]
    rng.shuffle(pool)
    for entry in pool:
        if len(library_index) >= target_size:
            break
        add_to_library(entry)

    by_id = {entry["id"]: entry for entry in catalog}
    rows: list[dict] = [{}] * len(library_index)
    for entry_id, filament_id in library_index.items():
        entry = by_id[entry_id]
        rows[filament_id] = {
            "filament_id": filament_id,
            "vendor_id": vendor_ids.get(entry["manufacturer"]),
            "vendor": entry.get("manufacturer"),
            "name": entry.get("name"),
            "material": entry.get("material"),
            "weight_g": entry.get("weight"),
            "diameter_mm": entry.get("diameter"),
            "colours": _entry_colours(entry),
        }

    rng.shuffle(cases)

    bad = _negatives_that_are_duplicates(rows, cases)
    if bad:
        msg = f"{len(bad)} negative case(s) are exact-tier duplicates of their own library row: {bad}"
        raise AssertionError(msg)

    return rows, cases


async def _run_filament_case(
    config: decision.DecisionConfig | None,
    rows: list[dict],
    case: FilamentCase,
) -> FilamentCaseResult:
    """Score one generated filament case; a decision-endpoint failure is recorded, not raised."""
    exact = duplicates._exact_filament(case.draft, case.colours, rows)  # noqa: SLF001
    exact_id = exact["filament_id"] if exact is not None else None
    if exact is not None or config is None:
        return FilamentCaseResult(case.typed, case.expected, case.kind, exact_id, None, None)

    reading = {
        "vendor": case.draft.vendor_name,
        "name": case.draft.name,
        "material": case.draft.material,
        "diameter_mm": case.draft.diameter,
    }
    ranked = spoolintake._rank_library(rows, reading, {})  # noqa: SLF001
    candidates = [
        row for row in ranked if duplicates.colour_relation(case.colours, row["colours"]) != "different colour"
    ]
    if not candidates:
        return FilamentCaseResult(case.typed, case.expected, case.kind, None, [], None)

    question = duplicates._filament_question(candidates, case.colours)  # noqa: SLF001
    match_candidates = [
        duplicates.Match(id=row["filament_id"], name=duplicates._filament_label(row))  # noqa: SLF001
        for row in candidates
    ]
    state = {key: value for key, value in reading.items() if value}
    try:
        answer = (await decision.ask_choices(config, state, {"filament": question}))["filament"]
    except decision.DecisionError as exc:
        return FilamentCaseResult(case.typed, case.expected, case.kind, None, match_candidates, None, error=str(exc))
    return FilamentCaseResult(case.typed, case.expected, case.kind, None, match_candidates, answer)


def _print_filament_report(results: list[FilamentCaseResult]) -> None:
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

    other_colour = [r for r in results if r.kind == "negative_colour"]
    if other_colour:
        print()
        scores = _score(other_colour, lambda r: r.model_pick(duplicates.SUGGEST_MIN_PROBABILITY))
        print(
            "Other-colour false-warning rate (same product, a real different colour or none set "
            f"yet; shipped threshold): {_fmt(scores.false_warning_rate)}",
        )


async def _main_filaments(*, catalog_path: Path, seed: int, count: int, baseline_only: bool) -> int:
    config = None
    if not baseline_only:
        config = decision.resolve_env_config()
        if config is None:
            print(_NO_ENDPOINT, file=sys.stderr)
            return 2

    if not catalog_path.is_file():
        print(f"Catalogue file not found: {catalog_path}", file=sys.stderr)
        return 2
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not catalog:
        print(f"No catalogue entries found in {catalog_path}.", file=sys.stderr)
        return 2

    rows, cases = _build_filament_dataset(catalog, seed=seed, count=count)
    if not cases:
        print("No filament cases could be generated from this catalogue.", file=sys.stderr)
        return 2

    results = [await _run_filament_case(config, rows, case) for case in cases]
    _print_filament_report(results)

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
    parser.add_argument("--filaments", action="store_true", help="evaluate the filament tier instead of vendors")
    parser.add_argument("--catalog", type=Path, help="a SpoolmanDB filaments.json to build filament cases from")
    parser.add_argument("--seed", type=int, default=0, help="random seed for filament case generation")
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_FILAMENT_COUNT,
        help=f"number of filament cases to generate (default {DEFAULT_FILAMENT_COUNT})",
    )
    args = parser.parse_args()
    if args.filaments:
        if args.catalog is None:
            parser.error("--filaments requires --catalog PATH")
        sys.exit(
            asyncio.run(
                _main_filaments(
                    catalog_path=args.catalog,
                    seed=args.seed,
                    count=args.count,
                    baseline_only=args.baseline_only,
                ),
            ),
        )
    else:
        sys.exit(asyncio.run(_main(baseline_only=args.baseline_only)))


if __name__ == "__main__":
    main()
