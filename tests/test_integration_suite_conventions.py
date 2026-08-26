"""Guard the conventions the Docker integration suite depends on.

`tests_integration/` runs inside a container that mounts only `tests_integration/tests`
and installs four pinned packages. It never sees this repo's `pyproject.toml`, so
`[tool.pytest.ini_options] asyncio_mode = "auto"` does not apply there -- pytest-asyncio
runs in its default *strict* mode instead, where an `async def` test without an explicit
`@pytest.mark.asyncio` is not run but **failed**, with "async def functions are not
natively supported".

Combined with the tester's `--exitfirst` entrypoint, one unmarked async test aborts the
whole matrix leg. That is invisible locally, where asyncio_mode=auto makes the same file
pass, so it costs a full CI round trip to discover. This test closes that gap in the fast
suite instead.
"""

import re
from pathlib import Path

import pytest

INTEGRATION_TESTS = Path(__file__).resolve().parent.parent / "tests_integration" / "tests"
ASYNC_TEST = re.compile(r"^async def (test\w*)", re.MULTILINE)
MARKER = "@pytest.mark.asyncio"


def _async_tests_missing_markers(path: Path) -> list[str]:
    """Return the names of async tests in `path` that carry no asyncio marker."""
    lines = path.read_text().split("\n")
    missing = []
    for index, line in enumerate(lines):
        match = ASYNC_TEST.match(line)
        if not match:
            continue
        # Walk back over the decorator stack; a blank line or plain code ends it.
        decorators = []
        cursor = index - 1
        while cursor >= 0 and lines[cursor].lstrip().startswith("@"):
            decorators.append(lines[cursor])
            cursor -= 1
        if not any(MARKER in decorator for decorator in decorators):
            missing.append(match.group(1))
    return missing


def _integration_test_files() -> list[Path]:
    return sorted(INTEGRATION_TESTS.rglob("test_*.py"))


def test_the_integration_suite_exists() -> None:
    """Fail loudly if the suite moves, rather than silently guarding nothing."""
    assert INTEGRATION_TESTS.is_dir(), f"{INTEGRATION_TESTS} not found"
    assert _integration_test_files(), "no integration test files found to check"


@pytest.mark.parametrize("path", _integration_test_files(), ids=lambda p: p.name)
def test_async_integration_tests_are_marked(path: Path) -> None:
    """Every async test in the Docker suite must be explicitly marked."""
    missing = _async_tests_missing_markers(path)
    assert not missing, (
        f"{path.relative_to(INTEGRATION_TESTS.parent.parent)} has async tests without "
        f"{MARKER}: {', '.join(missing)}. The tester container runs pytest-asyncio in "
        f"strict mode (it never sees pyproject.toml), where these fail rather than run, "
        f"and --exitfirst turns the first one into a failed CI matrix leg."
    )
