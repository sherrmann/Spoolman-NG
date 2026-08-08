"""Tool-selection eval for the curated agent layer.

Growing the tool surface trades reach for tool-selection accuracy on small local models, and
Spoolman's whole AI premise is "point it at your own Ollama". This turns that trade into a
number: each fixture prompt is sent with the real tool schemas, and we check which tool the
model reached for. It needs a live endpoint, so it is not part of CI — run it before a release
and whenever the tool set changes.

    poe ai-eval --min-accuracy 0.8
"""

# ruff: noqa: T201  (this is a CLI report; print is the point)

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Run directly as `python scripts/ai_eval.py` (poe's invocation, and the documented one) rather
# than as an installed package: CPython puts the *script's* directory on sys.path[0], not the
# repo root, and spoolman is not pip-installed here — so the repo root has to be added by hand
# before the local-package import below can resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spoolman import ai, ai_tools, aichat

CASES_PATH = Path(__file__).with_name("ai_eval_cases.json")

#: The eval must measure what the product actually ships: a writer-capable admin, English UI
#: locale (the fixtures are all English prompts), no page context (a fixture is asked cold, not
#: from a page that already narrows the intent). Building this from aichat._system_prompt itself,
#: rather than a hand-written one-liner, means a prompt change (e.g. new disambiguation guidance)
#: is automatically measured here too instead of silently drifting out of what's actually tested.
_EVAL_SYSTEM_PROMPT = aichat._system_prompt(context=None, locale="en", can_write=True)  # noqa: SLF001

#: Value returned in the confusion table / "called" slot when the model made no tool call,
#: called something unknown, or the request itself failed.
NO_CALL = "<none>"


#: Mirrors spoolman.ai_tools.base.arg_bool's accepted strings exactly, so a value this eval
#: scores as a boolean match is one the real tool would also have accepted.
_TRUE_STRINGS = ("true", "yes", "1")
_FALSE_STRINGS = ("false", "no", "0", "")


def _coerce_bool(value: object) -> bool | None:
    """Best-effort read of a model's boolean-ish value; None when it isn't recognizably one.

    ``bool(value)`` is not this: ``bool("nope")`` and ``bool("false")`` are both ``True``, since
    any non-empty string is truthy in Python regardless of its content. That would score a
    garbage string as a match against ``want=True`` and a *correct* ``"false"`` as a mismatch
    against ``want=False`` -- exactly backwards. None (not a recognized bool at all) matches
    neither True nor False, so an unrecognized value is always scored as a mismatch rather than
    passing by accident.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    return None


def _value_matches(want: object, got: object) -> bool:  # noqa: PLR0911
    """Whether one expected argument value plausibly matches what the model sent.

    Defensive against exactly the failure modes a small local model produces: a numeric-looking
    expectation compared against a non-numeric or missing value must not raise, it must fail the
    match. ``want`` values that are themselves lists/dicts (e.g. create_order's ``lines``, a list
    of {filament_id, quantity, price_per_unit} objects -- the hardest argument shape in the tool
    set) recurse with the same partial-match semantics ``_args_match`` uses at the top level: only
    the keys named in ``want`` have to match, and each of those recurses through this same
    function, so a nested int/bool/string still gets its own tolerant comparison rather than a
    brittle exact-equality check that would fail on "3" vs 3 or an extra key the model added.
    """
    if isinstance(want, str):
        return str(want).strip().lower() in str(got).strip().lower()
    if isinstance(want, bool):
        return _coerce_bool(got) is want
    if isinstance(want, (int, float)):
        try:
            return float(got) == float(want)
        except (TypeError, ValueError):
            # The model emitted something non-numeric ("twenty" instead of 20): a mismatch, not
            # a crash.
            return False
    if isinstance(want, list):
        return (
            isinstance(got, list)
            and len(got) == len(want)
            and all(_value_matches(w_item, g_item) for w_item, g_item in zip(want, got, strict=True))
        )
    if isinstance(want, dict):
        return isinstance(got, dict) and _args_match(want, got)
    return got == want


def _args_match(expected: dict, actual: dict) -> bool:
    """Whether every expected argument is present in ``actual`` and matches per ``_value_matches``."""
    return all(key in actual and _value_matches(want, actual[key]) for key, want in expected.items())


def _parse_tool_arguments(raw: object) -> dict:
    """Best-effort decode of a tool call's ``arguments`` payload into a dict.

    Small local models occasionally emit malformed JSON (unquoted keys, trailing commas, a bare
    string) in tool-call arguments — that is a real thing this harness exists to catch, not a
    reason for the whole 50+ case run to crash on case 12. Anything that doesn't decode to a
    dict is treated as "no usable arguments" rather than propagating the exception.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


#: Synthetic tool results for a legitimate precursor call, each chosen to leave exactly one
#: sensible next step. The empty lists are load-bearing: returning an *existing* vendor would make
#: "don't create it" the correct behaviour, and the fixtures expect a create — turn two would then
#: measure nothing. catalog_lookup returns the density/diameter the system prompt forbids inventing,
#: which is what unblocks create_filament.
_PRECURSOR_RESULTS = {
    "find_vendors": {"vendors": [], "total": 0},
    "find_locations": {"locations": [], "total": 0},
    "find_filaments": {"filaments": [{"id": 1, "name": "Example", "vendor": "Example"}], "total": 1},
    "find_spools": {"spools": [{"id": 1, "filament_id": 1, "remaining_weight": 500}], "total": 1},
    "find_orders": {"orders": [{"id": 1, "status": "ordered"}], "total": 1},
    "catalog_lookup": {
        "matches": [{"vendor": "Example", "name": "Example", "material": "PLA", "density": 1.24, "diameter": 1.75}],
    },
}


def _precursor_result(tool: str) -> str:
    """Tool-result content for a precursor call, as the JSON string the API expects."""
    return json.dumps(_PRECURSOR_RESULTS.get(tool, {}))


@dataclass
class CaseOutcome:
    """How one fixture went.

    ``direct`` and ``completed`` are deliberately separate. The system prompt tells the model to
    look before it writes; a model that follows that instruction is not wrong, it just did not go
    straight there. Collapsing both into one number scores instructed behaviour as failure and
    ranks careful models below eager ones.
    """

    direct: bool
    completed: bool
    args_ok: bool
    called: str


def _first_call(assistant: dict) -> tuple[str, dict]:
    """Name and parsed arguments of the assistant's first tool call, or (NO_CALL, {}).

    Only the first call is scored, but a model may legitimately emit several in parallel; the
    fixtures all describe a single intended action, so extras are ignored rather than failed.
    """
    calls = assistant.get("tool_calls") or []
    if not calls:
        return NO_CALL, {}
    function = calls[0].get("function", {})
    return function.get("name") or NO_CALL, _parse_tool_arguments(function.get("arguments"))


async def _run_case(config: ai.AIConfig, tools: list[dict], case: dict) -> CaseOutcome:
    """Score one fixture, allowing one follow-up turn after a declared precursor call.

    A request failure (endpoint hiccup, timeout) is scored as an incorrect call rather than
    raised: one flaky request must not abort the rest of the eval.
    """
    messages: list[dict] = [
        {"role": "system", "content": _EVAL_SYSTEM_PROMPT},
        {"role": "user", "content": case["prompt"]},
    ]
    try:
        assistant = await ai.chat_completion_tools(config, messages, tools=tools)
    except ai.AIRequestError as exc:
        return CaseOutcome(direct=False, completed=False, args_ok=False, called=f"<request error: {exc}>")

    called, parsed = _first_call(assistant)
    if called == case["tool"]:
        args_ok = _args_match(case.get("args", {}), parsed)
        return CaseOutcome(direct=True, completed=True, args_ok=args_ok, called=called)

    # One follow-up turn, and only when the model opened with a precursor this fixture declares.
    # Any other wrong tool ends here: the second turn exists to let instructed lookups finish the
    # task, not to become a retry that launders bad tool selection into a pass.
    if called not in case.get("precursors", []):
        return CaseOutcome(direct=False, completed=False, args_ok=False, called=called)

    messages.append({"role": "assistant", "content": None, "tool_calls": assistant.get("tool_calls")})
    messages.extend(
        {
            "role": "tool",
            "tool_call_id": call.get("id", "call_0"),
            "content": _precursor_result(call.get("function", {}).get("name", "")),
        }
        for call in assistant.get("tool_calls") or []
    )
    try:
        assistant = await ai.chat_completion_tools(config, messages, tools=tools)
    except ai.AIRequestError:
        return CaseOutcome(direct=False, completed=False, args_ok=False, called=called)

    second, parsed = _first_call(assistant)
    completed = second == case["tool"]
    return CaseOutcome(
        direct=False,
        completed=completed,
        args_ok=completed and _args_match(case.get("args", {}), parsed),
        called=called if not completed else f"{called} -> {second}",
    )


def _config_from_env() -> ai.AIConfig | None:
    """Build the eval's provider config from environment variables.

    Deliberately env-only rather than ai.resolve_config: that needs a database session, and an
    eval harness has no business opening the app's database to read UI settings. The trade-off
    is explicit — a key configured only through Settings -> AI is not picked up here.
    """
    config = ai.AIConfig(
        base_url=os.environ.get("SPOOLMAN_AI_BASE_URL"),
        api_key=os.environ.get("SPOOLMAN_AI_API_KEY"),
        model=os.environ.get("SPOOLMAN_AI_MODEL"),
    )
    return config if config.configured else None


def _print_report(per_tool: dict[str, list[CaseOutcome]], confusion: Counter, total: int) -> int:
    """Print the headline numbers, per-tool table and confusion table; return the completed count.

    Two headline numbers, not one. *Completed* is the honest measure of whether the assistant does
    the job; *direct* says whether it went straight there. A model that follows the prompt's
    look-before-you-write instruction scores lower on direct and full marks on completed, and
    reporting only the first would rank careful models below eager ones.
    """
    outcomes = [outcome for results in per_tool.values() for outcome in results]
    completed = sum(outcome.completed for outcome in outcomes)
    direct = sum(outcome.direct for outcome in outcomes)
    args_ok = sum(outcome.args_ok for outcome in outcomes)
    print(f"\nCompleted task:  {completed}/{total} ({completed / total:.0%})")
    print(f"  ...directly:   {direct}/{total} ({direct / total:.0%})")
    print(f"  ...with args:  {args_ok}/{total} ({args_ok / total:.0%})\n")
    for tool, results in sorted(per_tool.items(), key=lambda item: sum(o.completed for o in item[1]) / len(item[1])):
        done = sum(outcome.completed for outcome in results)
        straight = sum(outcome.direct for outcome in results)
        suffix = "" if done == straight else f"  ({straight} directly)"
        print(f"  {done}/{len(results)}  {tool}{suffix}")
    if confusion:
        print("\nConfusions (expected -> called):")
        for pair, count in confusion.most_common():
            print(f"  {count}x  {pair}")
    return completed


async def _main(min_accuracy: float) -> int:
    config = _config_from_env()
    if config is None:
        print("No AI endpoint configured. Set SPOOLMAN_AI_BASE_URL and SPOOLMAN_AI_MODEL.", file=sys.stderr)
        return 2

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not cases:
        print(f"No fixture cases found in {CASES_PATH}.", file=sys.stderr)
        return 2

    tools = ai_tools.tool_schemas(can_write=True)
    per_tool: dict[str, list[CaseOutcome]] = {}
    confusion: Counter = Counter()

    for case in cases:
        outcome = await _run_case(config, tools, case)
        per_tool.setdefault(case["tool"], []).append(outcome)
        if not outcome.completed:
            confusion[f"{case['tool']} -> {outcome.called}"] += 1

    total = len(cases)
    completed = _print_report(per_tool, confusion, total)

    # Gate on completion: finishing the task is the product-relevant behaviour, and a model that
    # looks something up first is still doing its job.
    return 0 if completed / total >= min_accuracy else 1


def main() -> None:
    """Entry point for `poe ai-eval`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-accuracy", type=float, default=0.8)
    sys.exit(asyncio.run(_main(parser.parse_args().min_accuracy)))


if __name__ == "__main__":
    main()
