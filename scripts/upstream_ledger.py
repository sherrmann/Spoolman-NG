"""Regenerate docs/upstream/SOLVED.md + ledger.json from the triage doc and live GitHub state.

Design: docs/superpowers/specs/2026-07-15-org-process-layer-design.md (section A).
Stdlib-only; external I/O goes through `git` and `gh` subprocesses (GitHubClient below).
"""

from __future__ import annotations

import dataclasses
import re


@dataclasses.dataclass
class TriageRow:
    fork_issue: int
    kind: str
    pri: str
    effort: str
    upstream: list[int]
    title: str


@dataclasses.dataclass
class SkipRow:
    upstream: int
    reason: str
    title: str


_LINK = re.compile(r"\[#(\d+)\]")
_BOLD_TITLE = re.compile(r"\*\*(.+?)\*\*")


def _title(cell: str) -> str:
    m = _BOLD_TITLE.search(cell)
    return m.group(1) if m else cell[:80]


def parse_triage(text: str) -> tuple[list[TriageRow], list[SkipRow]]:
    """Parse the two tables of docs/upstream-triage.md. Data rows all start with '| ['."""
    rows: list[TriageRow] = []
    skips: list[SkipRow] = []
    section: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            section = "actionable" if "Actionable" in line else "skipped" if "Skipped" in line else None
            continue
        if section is None or not line.startswith("| ["):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if section == "actionable":
            rows.append(
                TriageRow(
                    fork_issue=int(_LINK.search(cells[0]).group(1)),
                    kind=cells[1],
                    pri=cells[2],
                    effort=cells[3],
                    upstream=[int(n) for n in _LINK.findall(cells[4])],
                    title=_title(cells[5]),
                )
            )
        else:
            skips.append(
                SkipRow(upstream=int(_LINK.search(cells[0]).group(1)), reason=cells[1], title=_title(cells[2])),
            )
    return rows, skips
