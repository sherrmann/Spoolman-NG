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
from pathlib import Path

# Run directly as `python scripts/ai_eval.py` (poe's invocation, and the documented one) rather
# than as an installed package: CPython puts the *script's* directory on sys.path[0], not the
# repo root, and spoolman is not pip-installed here — so the repo root has to be added by hand
# before the local-package import below can resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spoolman import ai, ai_tools

CASES_PATH = Path(__file__).with_name("ai_eval_cases.json")

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


def _value_matches(want: object, got: object) -> bool:
    """Whether one expected argument value plausibly matches what the model sent.

    Defensive against exactly the failure modes a small local model produces: a numeric-looking
    expectation compared against a non-numeric or missing value must not raise, it must fail the
    match. ``want`` values that are themselves lists/dicts (e.g. create_order's ``lines``) fall
    back to plain equality rather than the numeric coercion below, which would otherwise raise
    ``TypeError`` on ``float(list)`` and abort the whole run over one fixture.
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


async def _run_case(config: ai.AIConfig, tools: list[dict], case: dict) -> tuple[bool, bool, str]:
    """Return (tool_correct, args_correct, tool_called) for one fixture case.

    A request failure (endpoint hiccup, timeout) is scored as an incorrect call rather than
    raised: one flaky request must not abort the rest of the eval.
    """
    messages = [
        {"role": "system", "content": "You are Spoolman's assistant. Use the tools to answer."},
        {"role": "user", "content": case["prompt"]},
    ]
    try:
        assistant = await ai.chat_completion_tools(config, messages, tools=tools)
    except ai.AIRequestError as exc:
        return False, False, f"<request error: {exc}>"

    calls = assistant.get("tool_calls") or []
    if not calls:
        return False, False, NO_CALL
    called = calls[0].get("function", {}).get("name") or NO_CALL
    parsed = _parse_tool_arguments(calls[0].get("function", {}).get("arguments"))
    tool_ok = called == case["tool"]
    return tool_ok, tool_ok and _args_match(case.get("args", {}), parsed), called


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


def _print_report(per_tool: dict[str, list[bool]], confusion: Counter, args_ok: int, total: int) -> int:
    """Print the headline numbers, per-tool table and confusion table; return the correct count."""
    correct = sum(sum(results) for results in per_tool.values())
    print(f"\nTool selection: {correct}/{total} ({correct / total:.0%})")
    print(f"Arguments too:  {args_ok}/{total} ({args_ok / total:.0%})\n")
    for tool, results in sorted(per_tool.items(), key=lambda item: sum(item[1]) / len(item[1])):
        print(f"  {sum(results)}/{len(results)}  {tool}")
    if confusion:
        print("\nConfusions (expected -> called):")
        for pair, count in confusion.most_common():
            print(f"  {count}x  {pair}")
    return correct


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
    per_tool: dict[str, list[bool]] = {}
    confusion: Counter = Counter()
    args_ok = 0

    for case in cases:
        tool_ok, arg_ok, called = await _run_case(config, tools, case)
        per_tool.setdefault(case["tool"], []).append(tool_ok)
        args_ok += int(arg_ok)
        if not tool_ok:
            confusion[f"{case['tool']} -> {called}"] += 1

    total = len(cases)
    correct = _print_report(per_tool, confusion, args_ok, total)

    return 0 if correct / total >= min_accuracy else 1


def main() -> None:
    """Entry point for `poe ai-eval`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-accuracy", type=float, default=0.8)
    sys.exit(asyncio.run(_main(parser.parse_args().min_accuracy)))


if __name__ == "__main__":
    main()
