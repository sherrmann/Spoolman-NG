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
