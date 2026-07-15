"""Tests for scripts/upstream_ledger.py (pure functions only — no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from upstream_ledger import parse_triage

FIXTURE = """
# Upstream backlog triage

## Actionable — one fork issue per row

| Fork issue | Kind | Pri | Effort | Covers upstream | Title / investigation summary |
|---|---|---|---|---|---|
| [#56](https://github.com/sherrmann/Spoolman-NG/issues/56) | feature | P1 | L | [#217](https://github.com/Donkie/Spoolman/issues/217) | **Add Bambu Lab AMS/Cloud integration** (high confidence) — details… |
| [#49](https://github.com/sherrmann/Spoolman-NG/issues/49) | feature | P1 | M | [#201](https://github.com/Donkie/Spoolman/issues/201), [#478](https://github.com/Donkie/Spoolman/issues/478) | **Show spool count per filament** — details… |

## Skipped — kept out of the tracker deliberately

| Upstream | Reason | Title / why |
|---|---|---|
| [#18](https://github.com/Donkie/Spoolman/issues/18) | already-implemented | **Mobile Support** — the fork ships a PWA… |
"""


def test_parse_triage_fixture() -> None:
    rows, skips = parse_triage(FIXTURE)
    assert [r.fork_issue for r in rows] == [56, 49]
    assert rows[0].upstream == [217]
    assert rows[0].kind == "feature"
    assert rows[0].pri == "P1"
    assert rows[0].effort == "L"
    assert rows[0].title == "Add Bambu Lab AMS/Cloud integration"
    assert rows[1].upstream == [201, 478]
    assert len(skips) == 1
    assert skips[0].upstream == 18
    assert skips[0].reason == "already-implemented"
    assert skips[0].title == "Mobile Support"


def test_parse_triage_real_document() -> None:
    text = (Path(__file__).parents[1] / "docs" / "upstream-triage.md").read_text()
    rows, skips = parse_triage(text)
    assert len(rows) == 98  # header: "98 fork issues filed"
    assert len(skips) == 133  # header: "133 SKIP"
    by_fork = {r.fork_issue: r for r in rows}
    assert by_fork[56].upstream == [217]
