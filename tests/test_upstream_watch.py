"""Tests for scripts/upstream_watch.py (pure functions only)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from upstream_watch import filter_created_after, render_watch_issue


def test_render_empty_is_none() -> None:
    assert render_watch_issue([], [], []) is None


def test_render_body_backticks_refs_and_lists_all() -> None:
    commits = [{"sha": "a" * 40, "subject": "Fix theme", "dirs": ["client", "spoolman"]}]
    issues = [{"number": 970, "title": "New issue", "created_at": "2026-07-12T10:00:00Z"}]
    prs = [{"number": 971, "title": "New PR", "created_at": "2026-07-13T10:00:00Z"}]
    body = render_watch_issue(commits, issues, prs)
    assert "### New upstream commits (1)" in body
    assert f"- [ ] `{'a' * 9}` Fix theme (`client`, `spoolman`) — port / skip?" in body
    assert "`Donkie/Spoolman#970`" in body
    assert "`Donkie/Spoolman#971`" in body
    # zero un-backticked upstream refs (no cross-link spam from listings):
    assert "Donkie/Spoolman#" not in body.replace("`Donkie/Spoolman#", "")
    assert "github.com/Donkie" not in body


def test_filter_created_after() -> None:
    items = [
        {"number": 1, "created_at": "2026-07-05T00:00:00Z"},
        {"number": 2, "created_at": "2026-07-07T00:00:00Z"},
    ]
    assert [i["number"] for i in filter_created_after(items, "2026-07-06T00:00:00Z")] == [2]
