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
