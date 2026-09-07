"""Guard the contract that nothing in the backend or its migrations calls ``datetime.utcnow()``.

Every datetime column stores naive UTC, and the codebase gets its "now" for those columns and
for websocket event timestamps from ``spoolman.database.utils.utc_now`` (issue #385). The
deprecated ``utcnow`` classmethod produced the same naive form, so a stray call would not fail
any behavioural test -- it would only warn, and only until Python removes the method. Its
tempting replacement, ``datetime.now(timezone.utc)``, is worse: it is offset-aware, the ORM
drops the tzinfo on read-back, and comparing the two raises ``TypeError``. This test keeps both
out by rejecting the deprecated call form outright, so that the next person reaches for the
helper rather than either of them.

``DTZ003`` in ruff rejects the same call; this test exists so that the rule cannot be quietly
re-added to the ignore list without a test going red.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED_DIRS = (REPO_ROOT / "spoolman", REPO_ROOT / "migrations")
UTCNOW_CALL = re.compile(r"\.utcnow\s*\(")


def _python_files() -> list[Path]:
    return sorted(path for directory in SCANNED_DIRS for path in directory.rglob("*.py"))


def test_the_scanned_directories_exist() -> None:
    """Fail loudly if the layout moves, rather than silently guarding nothing."""
    for directory in SCANNED_DIRS:
        assert directory.is_dir(), f"{directory} not found"
    assert _python_files(), "no Python files found to scan"


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_utcnow_call(path: Path) -> None:
    offending = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if UTCNOW_CALL.search(line)
    ]
    assert not offending, "datetime.utcnow() is deprecated; use spoolman.database.utils.utc_now():\n" + "\n".join(
        offending,
    )
