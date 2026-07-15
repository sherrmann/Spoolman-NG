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


from upstream_ledger import (  # noqa: E402
    SkipRow,
    TriageRow,
    build_ledger,
    parse_trailers,
    render_release_section,
    render_solved_md,
    upstream_refs_from_body,
)


def test_upstream_refs_from_body() -> None:
    body = (
        "> sweep\n"
        "**Upstream:** `Donkie/Spoolman#843` — 0 reactions\n"
        "Upstream: https://github.com/Donkie/Spoolman/issues/901\n"
        "unrelated Donkie/Spoolman#999 mention\n"
    )
    assert upstream_refs_from_body(body) == [843, 901]
    assert upstream_refs_from_body(None) == []


def test_parse_trailers() -> None:
    body = "Ports two things.\nUpstream-commit: abc1234 ported\nUpstream-commit: def5678 skipped — fork has own theme\n"
    assert parse_trailers(body) == [("abc1234", "ported", ""), ("def5678", "skipped", "fork has own theme")]


def _node(number: int, state: str, body: str = "", prs: list | None = None) -> dict:
    return {
        "number": number,
        "state": state,
        "body": body,
        "closedByPullRequestsReferences": {"nodes": prs or []},
    }


def test_build_and_render() -> None:
    rows = [
        TriageRow(56, "feature", "P1", "L", [217], "Bambu"),
        TriageRow(61, "fix", "P2", "S", [299], "Heavier spool"),
    ]
    skips = [SkipRow(18, "already-implemented", "Mobile Support")]
    states = {
        56: _node(
            56, "CLOSED", "**Upstream:** `Donkie/Spoolman#217`", [{"number": 200, "mergeCommit": {"oid": "beef"}}]
        ),
        61: _node(61, "OPEN", "**Upstream:** `Donkie/Spoolman#299`"),
        # created after the sweep, carries its own marker:
        150: _node(
            150,
            "CLOSED",
            "Upstream: https://github.com/Donkie/Spoolman/issues/901",
            [{"number": 210, "mergeCommit": {"oid": "cafe"}}],
        ),
    }
    trailer_prs = [{"number": 220, "body": "Upstream-commit: abc1234 ported", "mergeCommit": {"oid": "f00d"}}]
    ledger = build_ledger(rows, skips, states, trailer_prs, release_of=lambda oid: "v2026.7.9" if oid else "")
    solved_forks = {e["fork_issue"] for e in ledger["solved"]}
    assert solved_forks == {56, 150}
    assert {e["fork_issue"] for e in ledger["in_progress"]} == {61}
    e56 = next(e for e in ledger["solved"] if e["fork_issue"] == 56)
    assert e56["pr"] == 200
    assert e56["released_in"] == "v2026.7.9"
    assert e56["upstream"] == [217]
    assert ledger["upstream_commits"] == [
        {"sha": "abc1234", "verdict": "ported", "reason": "", "pr": 220, "released_in": "v2026.7.9"}
    ]
    md = render_solved_md(ledger)
    assert "Donkie/Spoolman#217" in md
    assert "#56" in md
    assert "v2026.7.9" in md
    assert "already-implemented" in md
    section = render_release_section(ledger, "v2026.7.9")
    assert "#217" in section
    assert "#901" in section
    assert render_release_section(ledger, "v9999.1.1") == ""
