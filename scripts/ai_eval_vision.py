"""Scan-to-Spool extraction eval (`poe ai-eval-vision`).

The sibling of ai_eval.py for the photo path. Scan-to-Spool has no automated coverage against a
real model at all, and its failure mode is quiet: a model that cannot satisfy the strict-JSON
contract, or that needs longer than the request timeout, produces an error the user sees as "the
scan didn't work" with nothing in the logs to say why.

Runs photos through ``spoolintake.extract`` itself — same prompt, same data-URL shape, same
normalisation — so a pass here is a pass for the feature rather than for a stand-in. Like
`poe ai-eval` it needs a live endpoint, so it is not part of CI.

    SPOOLMAN_AI_BASE_URL=http://localhost:11434/v1 SPOOLMAN_AI_MODEL=qwen2.5vl:7b poe ai-eval-vision

Only a synthetic label ships with the repo. It is a *floor* test: flat, perfectly framed, high
contrast, so a model that fails it cannot read a real spool either — one measured model completed
every photo and still scored 0/10 here. Real photos are the harder and more informative half, and
they are personal, so point the harness at your own directory instead:

    poe ai-eval-vision --photos ~/my-spool-photos

That directory needs a cases.json in the same shape as scripts/ai_eval_vision_cases/cases.json.

Pass ``--dump-extractions FILE`` to also write each successfully-extracted photo's normalised
extraction as a JSON line to FILE, in case order, for scripts/match_rerank_eval.py --photos. A
photo whose extraction failed is left out; the file is overwritten at the start of the run. A case
may leave out ``want`` when it is only there for that: it then counts towards completion alone.
"""

# ruff: noqa: T201  (this is a CLI report; print is the point)

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spoolman import ai, spoolintake

DEFAULT_CASES = Path(__file__).with_name("ai_eval_vision_cases")

#: Only these four fields feed spoolintake.score_candidate (name 0.4, vendor 0.3, material 0.2,
#: weight 0.1), so they decide whether a scan finds the right filament. The rest are pre-fill the
#: user can correct on the confirm card. A flat field count hides that difference, and a
#: *confidently wrong* value in one of these is worse than a blank one — it silently drags the
#: match toward the wrong record.
MATCH_FIELDS = ("name", "vendor", "material", "weight_g")


def _matches(expected: object, actual: object) -> bool:
    """Whether one expected value plausibly matches what the model returned."""
    options = expected if isinstance(expected, list) else [expected]
    for option in options:
        if option is None and actual is None:
            return True
        if isinstance(option, str) and isinstance(actual, str) and option.lower() in actual.lower():
            return True
        if isinstance(option, (int, float)) and isinstance(actual, (int, float)) and float(option) == float(actual):
            return True
    return False


async def _run_case(config: ai.AIConfig, folder: Path, case: dict) -> tuple[bool, int, int, int, dict | None]:
    """Return (completed, fields_ok, fields_total, match_fields_ok, extraction) for one photo.

    ``extraction`` is the normalised dict `spoolintake.extract` returned, or None when extraction
    failed -- the caller uses it for ``--dump-extractions`` without re-running the request.
    """
    image = base64.b64encode((folder / case["file"]).read_bytes()).decode()
    started = time.perf_counter()
    try:
        got = await spoolintake.extract(config, image, "image/jpeg")
    except (ai.AIRequestError, spoolintake.ExtractionParseError) as exc:
        print(f"  FAILED after {time.perf_counter() - started:.1f}s  {case['file']}: {exc}")
        return False, 0, len(case.get("want", {})), 0, None

    elapsed = time.perf_counter() - started
    want = case.get("want", {})
    hits = sum(_matches(expected, got.get(field)) for field, expected in want.items())
    match_hits = sum(_matches(expected, got.get(field)) for field, expected in want.items() if field in MATCH_FIELDS)
    print(f"  {elapsed:6.1f}s  {hits}/{len(want)} fields  {case['file']}  ({case.get('what', '')})")
    for field, expected in want.items():
        actual = got.get(field)
        if not _matches(expected, actual):
            flag = "  <-- match-critical" if field in MATCH_FIELDS else ""
            print(f"           miss  {field}: wanted {expected!r}, got {actual!r}{flag}")
    return True, hits, len(want), match_hits, got


async def _main(photos: Path, min_completion: float, dump_extractions: Path | None) -> int:
    config = ai.AIConfig(
        base_url=os.environ.get("SPOOLMAN_AI_BASE_URL"),
        api_key=os.environ.get("SPOOLMAN_AI_API_KEY"),
        model=os.environ.get("SPOOLMAN_AI_MODEL"),
        vision_model=os.environ.get("SPOOLMAN_AI_VISION_MODEL"),
    )
    if not config.configured:
        print("No AI endpoint configured. Set SPOOLMAN_AI_BASE_URL and SPOOLMAN_AI_MODEL.", file=sys.stderr)
        return 2

    cases_file = photos / "cases.json"
    if not cases_file.is_file():
        print(f"No cases.json in {photos}.", file=sys.stderr)
        return 2
    cases = json.loads(cases_file.read_text(encoding="utf-8"))
    if not cases:
        print(f"No cases found in {cases_file}.", file=sys.stderr)
        return 2

    print(f"model={config.vision_model or config.model}  photos={photos}  cases={len(cases)}\n")
    if dump_extractions is not None:
        dump_extractions.write_text("", encoding="utf-8")  # overwrite at the start of the run

    completed = fields_ok = fields_total = match_ok = 0
    for case in cases:
        ok, hits, total, match_hits, extraction = await _run_case(config, photos, case)
        completed += int(ok)
        fields_ok += hits
        fields_total += total
        match_ok += match_hits
        if dump_extractions is not None and extraction is not None:
            line = json.dumps({"file": case["file"], "extraction": extraction})
            with dump_extractions.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    match_total = sum(1 for case in cases for field in case.get("want", {}) if field in MATCH_FIELDS)
    print(f"\nCompleted:       {completed}/{len(cases)}")
    print(f"Fields correct:  {fields_ok}/{fields_total}")
    print(f"  match-critical:{match_ok}/{match_total}  (name/vendor/material/weight — what finds the filament)")

    return 0 if completed / len(cases) >= min_completion else 1


def main() -> None:
    """Entry point for `poe ai-eval-vision`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photos", type=Path, default=DEFAULT_CASES, help="directory holding cases.json + images")
    parser.add_argument("--min-completion", type=float, default=1.0, help="fail below this completion rate")
    parser.add_argument(
        "--dump-extractions",
        type=Path,
        default=None,
        help="write each successfully-extracted photo's normalised extraction as a JSON line to this file",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.photos, args.min_completion, args.dump_extractions)))


if __name__ == "__main__":
    main()
