"""Import guard for scripts/ai_eval.py (`poe ai-eval`).

The eval needs a live endpoint, so it is deliberately out of CI and nothing else imports it —
which means a rename or signature change in the private helpers it reaches into
(``aichat._system_prompt``) breaks `poe ai-eval` at import time with nobody noticing until
someone runs it before a release. The script builds its system prompt at *module scope*, so
simply importing it is a real check that the seam still holds.
"""

import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from spoolman import ai_tools

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ai_eval.py"


@pytest.fixture
def ai_eval_module() -> Iterator[ModuleType]:
    """Import scripts/ai_eval.py by path (it is a standalone script, not an installed package)."""
    spec = importlib.util.spec_from_file_location("_ai_eval_under_test", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # _EVAL_SYSTEM_PROMPT is built here, at module scope
        yield module
    finally:
        sys.modules.pop("_ai_eval_under_test", None)


def test_ai_eval_script_imports_and_builds_a_prompt(ai_eval_module: ModuleType) -> None:
    # The prompt must be the real shipped one, not an empty string or a stub: the whole point of
    # building it from aichat._system_prompt is that the eval measures what production sends.
    prompt = ai_eval_module._EVAL_SYSTEM_PROMPT  # noqa: SLF001 -- the module-scope value under test
    assert isinstance(prompt, str)
    assert len(prompt) > 200, "the eval's system prompt collapsed to something that isn't the shipped one"
    assert "Spoolman" in prompt


def test_ai_eval_cases_name_tools_that_still_exist(ai_eval_module: ModuleType) -> None:
    # The other half of the same seam: every fixture's expected tool must still exist in the
    # registry, or the eval scores real answers as wrong against a tool name that no longer means
    # anything. Cheap here, invisible when the eval only runs by hand before a release.
    cases = json.loads(ai_eval_module.CASES_PATH.read_text(encoding="utf-8"))
    assert cases
    known = set(ai_tools.READ_TOOLS) | set(ai_tools.WRITE_TOOLS)
    unknown = sorted({case["tool"] for case in cases} - known)
    assert not unknown, f"ai_eval_cases.json expects tools that no longer exist: {unknown}"


# --- Two-turn scoring (#380) -------------------------------------------------------
#
# The system prompt tells the model to look before it writes ("check find_vendors or
# find_locations before creating a vendor or location that may already exist", and to call
# catalog_lookup rather than invent a density). A single-turn harness scores that instructed
# behaviour as a failure and never reaches the write, which penalises careful models hardest --
# Sonnet 5 lost all five of its misses this way while following the prompt exactly.
#
# So a fixture may declare the precursor calls that legitimately come first. When the model opens
# with one, the harness feeds back a synthetic result and scores the *second* call, reporting
# "went straight there" and "completed the task" separately.


def test_precursor_results_leave_exactly_one_sensible_next_step(ai_eval_module: ModuleType) -> None:
    """A lookup that returns a hit would make *not* creating the record correct.

    The fixtures expect a create, so the synthetic answer has to say "no such record yet";
    otherwise turn two measures nothing and the model is right to stop.
    """
    for tool in ("find_vendors", "find_locations"):
        reply = json.loads(ai_eval_module._precursor_result(tool))  # noqa: SLF001
        assert reply, f"{tool} needs a result payload"
        assert not any(value for value in reply.values() if isinstance(value, list)), (
            f"{tool}'s synthetic result must be empty, or creating the record is no longer correct"
        )


def test_catalog_lookup_result_supplies_what_the_prompt_forbids_guessing(ai_eval_module: ModuleType) -> None:
    """create_filament is blocked on density/diameter the model is told never to invent."""
    reply = json.loads(ai_eval_module._precursor_result("catalog_lookup"))  # noqa: SLF001
    assert "density" in json.dumps(reply)
    assert "diameter" in json.dumps(reply)


async def test_a_precursor_then_the_expected_tool_counts_as_completed_but_not_direct(
    ai_eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies = [
        {"tool_calls": [{"function": {"name": "find_vendors", "arguments": "{}"}}]},
        {"tool_calls": [{"function": {"name": "create_vendor", "arguments": '{"name": "polymaker"}'}}]},
    ]

    async def _fake(*_args: object, **_kwargs: object) -> dict:
        return replies.pop(0)

    monkeypatch.setattr(ai_eval_module.ai, "chat_completion_tools", _fake)
    case = {
        "prompt": "Add Polymaker as a vendor",
        "tool": "create_vendor",
        "args": {"name": "polymaker"},
        "precursors": ["find_vendors"],
    }

    outcome = await ai_eval_module._run_case(ai_eval_module.ai.AIConfig(), [], case)  # noqa: SLF001

    assert outcome.direct is False, "it did not go straight to the write"
    assert outcome.completed is True, "but it did finish the task"
    assert outcome.args_ok is True


async def test_a_wrong_first_tool_never_gets_a_second_turn(
    ai_eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second turn must not become a retry that launders bad tool selection into a pass."""
    calls: list[object] = []

    async def _fake(*_args: object, **_kwargs: object) -> dict:
        calls.append(object())
        return {"tool_calls": [{"function": {"name": "delete_spool", "arguments": "{}"}}]}

    monkeypatch.setattr(ai_eval_module.ai, "chat_completion_tools", _fake)
    case = {"prompt": "Add Polymaker as a vendor", "tool": "create_vendor", "precursors": ["find_vendors"]}

    outcome = await ai_eval_module._run_case(ai_eval_module.ai.AIConfig(), [], case)  # noqa: SLF001

    assert len(calls) == 1, "a wrong tool must not earn another turn"
    assert outcome.direct is False
    assert outcome.completed is False


# --- Invented arguments (#380) -----------------------------------------------------
#
# `_args_match` only checks that the *expected* arguments are present, so a call that carries
# the right ones plus a pile of fabricated extras scores as a clean pass. Observed on
# qwen3:4b-instruct: "Record an order of 2x filament 6 at 19.50 each" produced the correct
# lines together with an invented shop, order number, date and comment -- and dropped the 19.50
# that was actually in the prompt. That would create a real order attributed to a shop the user
# never named.
#
# The heuristic is deliberately narrow: a *string* argument whose value does not appear in the
# prompt at all cannot have come from the user. Numbers are excluded (too many legitimate
# defaults and unit conversions) and so are booleans.


def test_a_string_argument_absent_from_the_prompt_is_reported_as_invented(ai_eval_module: ModuleType) -> None:
    invented = ai_eval_module._invented_args(  # noqa: SLF001
        "Record an order of 2x filament 6 at 19.50 each",
        {"lines": [{"filament_id": 6}], "shop": "PrintRight", "order_number": "ORD-2023-004"},
    )
    assert sorted(invented) == ["order_number", "shop"]


def test_arguments_the_user_actually_said_are_not_reported(ai_eval_module: ModuleType) -> None:
    """Matching must survive the casing and punctuation a model normalises away."""
    invented = ai_eval_module._invented_args(  # noqa: SLF001
        "Log an order: 4 spools of filament 10 from Filastruder, order number PO-2291",
        {"shop": "Filastruder", "order_number": "PO-2291"},
    )
    assert invented == []


def test_a_location_restated_with_different_capitalisation_is_not_invented(ai_eval_module: ModuleType) -> None:
    invented = ai_eval_module._invented_args("Order 7 turned up, put them in shelf A", {"location": "Shelf A"})  # noqa: SLF001
    assert invented == []


def test_numbers_and_booleans_are_never_reported(ai_eval_module: ModuleType) -> None:
    """A default quantity or a unit conversion is not fabrication; only free text is judged."""
    invented = ai_eval_module._invented_args("My order 4 arrived", {"order_id": 4, "create_spools": True})  # noqa: SLF001
    assert invented == []


def test_values_derived_from_the_prompt_are_not_called_invented(ai_eval_module: ModuleType) -> None:
    """The point is to catch fabrication, not derivation.

    A date range computed from "last month", a hex code derived from a colour word, and an enum
    the schema itself defines are all the model doing its job with values that cannot appear in
    the prompt verbatim. Flagging them buries the two real cases in six false ones.
    """
    enums = ai_eval_module._ENUM_ARG_NAMES  # noqa: SLF001
    assert "status" in enums, "find_orders.status is an enum and must be exempt"

    dates = ai_eval_module._invented_args(  # noqa: SLF001
        "How much did I use last month?",
        {"from_date": "2026-07-01", "to_date": "2026-07-31"},
    )
    assert dates == []
    assert ai_eval_module._invented_args("Show me my red spools", {"color_hex": "ff0000"}) == []  # noqa: SLF001
    assert ai_eval_module._invented_args("What is on order?", {"status": "open"}) == []  # noqa: SLF001


def test_a_fabricated_shop_is_still_reported(ai_eval_module: ModuleType) -> None:
    """The exemptions must not swallow the case this exists for."""
    invented = ai_eval_module._invented_args(  # noqa: SLF001
        "Record an order of 2x filament 6 at 19.50 each",
        {"shop": "PrintRight", "comment": "Replacement for outdoor project"},
    )
    assert sorted(invented) == ["comment", "shop"]


# --- Turn-two prose (#387) ----------------------------------------------------------


async def test_prose_after_a_precursor_is_captured_when_the_model_stalls(
    ai_eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stalling in prose is a different failure from calling the wrong tool.

    #387.3: both scored identically and both showed only the precursor in the confusion table,
    because the harness discarded the one thing that tells them apart - what the model said.
    """
    replies = [
        {"tool_calls": [{"function": {"name": "catalog_lookup", "arguments": "{}"}}]},
        {"content": "I found PLA at 1.24 g/cm3 and 1.75 mm. Shall I create it?", "tool_calls": []},
    ]

    async def _fake(*_args: object, **_kwargs: object) -> dict:
        return replies.pop(0)

    monkeypatch.setattr(ai_eval_module.ai, "chat_completion_tools", _fake)
    case = {
        "prompt": "Add Polymaker PolyLite PLA",
        "tool": "create_filament",
        "precursors": ["catalog_lookup"],
    }

    outcome = await ai_eval_module._run_case(ai_eval_module.ai.AIConfig(), [], case)  # noqa: SLF001

    assert outcome.completed is False
    assert outcome.stalled_prose is not None, "the prose that explains the stall must survive"
    assert "1.24" in outcome.stalled_prose


async def test_no_prose_is_recorded_when_the_model_completes(
    ai_eval_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies = [
        {"tool_calls": [{"function": {"name": "find_vendors", "arguments": "{}"}}]},
        {
            "content": "Creating it now.",
            "tool_calls": [{"function": {"name": "create_vendor", "arguments": '{"name": "polymaker"}'}}],
        },
    ]

    async def _fake(*_args: object, **_kwargs: object) -> dict:
        return replies.pop(0)

    monkeypatch.setattr(ai_eval_module.ai, "chat_completion_tools", _fake)
    case = {"prompt": "Add Polymaker as a vendor", "tool": "create_vendor", "precursors": ["find_vendors"]}

    outcome = await ai_eval_module._run_case(ai_eval_module.ai.AIConfig(), [], case)  # noqa: SLF001

    assert outcome.completed is True
    assert outcome.stalled_prose is None, "prose alongside a correct call is not a stall"
