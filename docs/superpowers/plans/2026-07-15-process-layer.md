# Spoolman-NG Process Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the fork's process layer: add-ons repo CI, an upstream-solved ledger, a weekly upstream watch, SpoolmanDB auto-sync, PR-based add-on version bumps, and the org-trial runbook — per `docs/superpowers/specs/2026-07-15-org-process-layer-design.md`.

**Architecture:** Two stdlib-only Python scripts in the main repo (`scripts/upstream_ledger.py`, `scripts/upstream_watch.py`) with pure, unit-tested cores and a thin `gh` CLI wrapper; four small GitHub Actions workflows (main repo ×2, addons ×1, SpoolmanDB ×1); repo-settings changes via `gh api`. The org migration is a manual runbook, gated.

**Tech Stack:** Python 3.10+ stdlib only, pytest (existing `tests/` dir), GitHub Actions, `gh` CLI (authenticated as sherrmann).

## Global Constraints

- Three working directories: main repo `/home/sam/spoolman/Spoolman`, add-ons `/home/sam/spoolman-ng-addons`, data `/home/sam/SpoolmanDB`. Every task states its repo; never assume.
- **Classic PAT stays** (spec decision 4). No new tokens are minted. Do not touch `secrets.PAT`.
- **Zero upstream footprint from generated content:** machine-generated issue bodies (watch issues) reference upstream as backticked `` `Donkie/Spoolman#NNN` `` so GitHub does NOT cross-link. Only human-authored work items use plain URLs (spec decision 2).
- Scripts are **stdlib-only** (no new deps in `pyproject.toml`); external I/O only via `subprocess` calls to `git` and `gh`.
- Bot commits to master use `[skip ci]` in the commit message.
- Monday cadence, staggered after the existing 04:00 mutation run: watch 05:00, ledger 05:30, SpoolmanDB sync 06:00 (all UTC).
- Main-repo work happens on branch `feat/process-layer` (created in Task 2; the two committed spec/plan docs ride along in its PR). Add-ons and SpoolmanDB commit straight to their default branches (their current convention) — but in Task 7, push the workflow **before** enabling branch protection.
- Fork repo slug for `gh`: `sherrmann/Spoolman-NG` (renamed; API resolves it).
- pytest runs from the main repo root: `uv run pytest tests/test_upstream_ledger.py -v` (testpaths is `tests`).

---

### Task 1: Add-ons repo CI + Dependabot

**Repo:** `/home/sam/spoolman-ng-addons`

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/dependabot.yml`

**Interfaces:**
- Produces: check-run names `lint` and `build-smoke` — Task 6's branch protection lists exactly these strings as required contexts.

- [ ] **Step 1: Fast-forward the local checkout (it is 9 behind origin)**

```bash
cd /home/sam/spoolman-ng-addons
git pull --ff-only
git log --oneline -1   # expect: bd73653 Bump Spoolman NG add-on to 2026.7.10
```

Leave the two untracked handoff `.md` files alone — out of scope.

- [ ] **Step 2: Write the CI workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [master]
  pull_request:

permissions:
  contents: read

jobs:
  lint:
    name: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Home Assistant add-on linter
        uses: frenck/action-addon-linter@v2
        with:
          path: ./spoolman_ng
  build-smoke:
    name: build-smoke
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Build the add-on image (amd64) from its declared base
        run: |
          BUILD_FROM=$(sed -n 's/^  amd64: //p' spoolman_ng/build.yaml)
          echo "Building FROM ${BUILD_FROM}"
          docker build --build-arg "BUILD_FROM=${BUILD_FROM}" -t addon-smoke spoolman_ng/
```

(Build-only smoke is deliberate: `run.sh` needs Supervisor's `/data/options.json` to boot, so a container-start test belongs to `TESTING.md`'s live paths, not CI.)

- [ ] **Step 3: Write the Dependabot config**

Create `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
  - package-ecosystem: docker
    directory: /spoolman_ng
    schedule:
      interval: weekly
```

- [ ] **Step 4: Validate YAML locally**

```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); yaml.safe_load(open('.github/dependabot.yml')); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit and push (direct to master — no protection exists yet)**

```bash
git add .github/
git commit -m "ci: add add-on linter + amd64 build smoke, enable Dependabot"
git push origin master
```

- [ ] **Step 6: Verify the run is green and capture check names**

```bash
gh run watch --repo sherrmann/spoolman-ng-addons --exit-status $(gh run list --repo sherrmann/spoolman-ng-addons --limit 1 --json databaseId --jq '.[0].databaseId')
gh api repos/sherrmann/spoolman-ng-addons/commits/master/check-runs --jq '.check_runs[].name'
```

Expected: run concludes `success`; check names printed are exactly `lint` and `build-smoke` (Task 6 depends on these strings — if they differ, fix the workflow `name:`/job ids, don't adapt Task 6).

---

### Task 2: Ledger — triage-table parser (TDD)

**Repo:** `/home/sam/spoolman/Spoolman` — start by branching: `git checkout -b feat/process-layer` (from local master, which already carries the spec/plan docs commits).

**Files:**
- Create: `scripts/upstream_ledger.py`
- Test: `tests/test_upstream_ledger.py`

**Interfaces:**
- Produces (used by Task 3 in the same module):
  - `TriageRow` dataclass: `fork_issue: int, kind: str, pri: str, effort: str, upstream: list[int], title: str`
  - `SkipRow` dataclass: `upstream: int, reason: str, title: str`
  - `parse_triage(text: str) -> tuple[list[TriageRow], list[SkipRow]]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_upstream_ledger.py`:

```python
"""Tests for scripts/upstream_ledger.py (pure functions only — no network)."""
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from upstream_ledger import parse_triage  # noqa: E402

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
    assert rows[0].kind == "feature" and rows[0].pri == "P1" and rows[0].effort == "L"
    assert rows[0].title == "Add Bambu Lab AMS/Cloud integration"
    assert rows[1].upstream == [201, 478]
    assert len(skips) == 1
    assert skips[0].upstream == 18 and skips[0].reason == "already-implemented"
    assert skips[0].title == "Mobile Support"


def test_parse_triage_real_document() -> None:
    text = (Path(__file__).parents[1] / "docs" / "upstream-triage.md").read_text()
    rows, skips = parse_triage(text)
    assert len(rows) == 98      # header: "98 fork issues filed"
    assert len(skips) == 133    # header: "133 SKIP"
    by_fork = {r.fork_issue: r for r in rows}
    assert by_fork[56].upstream == [217]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sam/spoolman/Spoolman
uv run pytest tests/test_upstream_ledger.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'upstream_ledger'`

- [ ] **Step 3: Implement the parser**

Create `scripts/upstream_ledger.py`:

```python
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
            skips.append(SkipRow(upstream=int(_LINK.search(cells[0]).group(1)), reason=cells[1], title=_title(cells[2])))
    return rows, skips
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_upstream_ledger.py -v
```

Expected: 2 passed. If `test_parse_triage_real_document` fails on the counts, the parser is wrong (the doc's own header states 98/133) — fix the parser, do not loosen the assertion.

- [ ] **Step 5: Commit**

```bash
git add scripts/upstream_ledger.py tests/test_upstream_ledger.py
git commit -m "feat(ledger): parse the upstream triage tables"
```

---

### Task 3: Ledger — live join, renderers, CLI

**Repo:** `/home/sam/spoolman/Spoolman`, branch `feat/process-layer`

**Files:**
- Modify: `scripts/upstream_ledger.py` (append)
- Modify: `tests/test_upstream_ledger.py` (append)
- Create (generated): `docs/upstream/SOLVED.md`, `docs/upstream/ledger.json`

**Interfaces:**
- Consumes: `parse_triage`, `TriageRow`, `SkipRow` (Task 2).
- Produces:
  - `upstream_refs_from_body(body: str | None) -> list[int]`
  - `parse_trailers(body: str | None) -> list[tuple[str, str, str]]` — (sha, verdict, reason)
  - `build_ledger(rows, skips, issue_states: dict[int, dict], trailer_prs: list[dict], release_of) -> dict`
  - `render_solved_md(ledger: dict) -> str`
  - `render_release_section(ledger: dict, tag: str) -> str`
  - CLI: `python3 scripts/upstream_ledger.py --check | --write | --release-notes TAG` (Task 4's workflow calls `--write` and `--release-notes`).
  - `issue_states` shape (GraphQL node per fork issue number): `{"number": int, "state": "OPEN"|"CLOSED", "body": str, "closedByPullRequestsReferences": {"nodes": [{"number": int, "mergeCommit": {"oid": str}}]}}`

- [ ] **Step 1: Write the failing tests (append to `tests/test_upstream_ledger.py`)**

```python
from upstream_ledger import (  # noqa: E402
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
    from upstream_ledger import TriageRow, SkipRow

    rows = [
        TriageRow(56, "feature", "P1", "L", [217], "Bambu"),
        TriageRow(61, "fix", "P2", "S", [299], "Heavier spool"),
    ]
    skips = [SkipRow(18, "already-implemented", "Mobile Support")]
    states = {
        56: _node(56, "CLOSED", "**Upstream:** `Donkie/Spoolman#217`", [{"number": 200, "mergeCommit": {"oid": "beef"}}]),
        61: _node(61, "OPEN", "**Upstream:** `Donkie/Spoolman#299`"),
        # created after the sweep, carries its own marker:
        150: _node(150, "CLOSED", "Upstream: https://github.com/Donkie/Spoolman/issues/901", [{"number": 210, "mergeCommit": {"oid": "cafe"}}]),
    }
    trailer_prs = [{"number": 220, "body": "Upstream-commit: abc1234 ported", "mergeCommit": {"oid": "f00d"}}]
    ledger = build_ledger(rows, skips, states, trailer_prs, release_of=lambda oid: "v2026.7.9" if oid else "")
    solved_forks = {e["fork_issue"] for e in ledger["solved"]}
    assert solved_forks == {56, 150}
    assert {e["fork_issue"] for e in ledger["in_progress"]} == {61}
    e56 = next(e for e in ledger["solved"] if e["fork_issue"] == 56)
    assert e56["pr"] == 200 and e56["released_in"] == "v2026.7.9" and e56["upstream"] == [217]
    assert ledger["upstream_commits"] == [
        {"sha": "abc1234", "verdict": "ported", "reason": "", "pr": 220, "released_in": "v2026.7.9"}
    ]
    md = render_solved_md(ledger)
    assert "Donkie/Spoolman#217" in md and "#56" in md and "v2026.7.9" in md
    assert "already-implemented" in md
    section = render_release_section(ledger, "v2026.7.9")
    assert "#217" in section and "#901" in section
    assert render_release_section(ledger, "v9999.1.1") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_upstream_ledger.py -v
```

Expected: FAIL — `ImportError: cannot import name 'build_ledger'`

- [ ] **Step 3: Implement (append to `scripts/upstream_ledger.py`)**

```python
import argparse
import json
import subprocess
import sys
from pathlib import Path

FORK_REPO = "sherrmann/Spoolman-NG"
UPSTREAM = "Donkie/Spoolman"

_REF_LINE = re.compile(r"^\s*\**Upstream:?\**", re.IGNORECASE)
_REF = re.compile(r"Donkie/Spoolman(?:#|/issues/)(\d+)")
_TRAILER = re.compile(
    r"Upstream-commit:\s*([0-9a-f]{7,40})\s+(ported|skipped)(?:\s*[—–-]\s*(\S.*?))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def upstream_refs_from_body(body: str | None) -> list[int]:
    refs: list[int] = []
    for line in (body or "").splitlines():
        if _REF_LINE.match(line):
            refs += [int(n) for n in _REF.findall(line)]
    return refs


def parse_trailers(body: str | None) -> list[tuple[str, str, str]]:
    return [(sha, verdict.lower(), (reason or "").strip()) for sha, verdict, reason in _TRAILER.findall(body or "")]


def build_ledger(rows, skips, issue_states, trailer_prs, release_of) -> dict:
    triaged = {r.fork_issue for r in rows}
    entries = [(r.fork_issue, r.upstream, r.title, r.kind, r.pri) for r in rows]
    # Issues filed after the sweep that carry their own Upstream: marker:
    for num, node in sorted(issue_states.items()):
        if num in triaged:
            continue
        refs = upstream_refs_from_body(node.get("body"))
        if refs:
            entries.append((num, refs, "", "", ""))

    solved, in_progress = [], []
    for fork_issue, upstream, title, kind, pri in entries:
        node = issue_states.get(fork_issue)
        refs = sorted(set(upstream) | set(upstream_refs_from_body(node.get("body")) if node else []))
        entry = {"fork_issue": fork_issue, "upstream": refs, "title": title, "kind": kind, "pri": pri}
        if node and node["state"] == "CLOSED":
            prs = node["closedByPullRequestsReferences"]["nodes"]
            entry["pr"] = prs[0]["number"] if prs else None
            entry["released_in"] = release_of(prs[0]["mergeCommit"]["oid"]) if prs and prs[0].get("mergeCommit") else None
            solved.append(entry)
        else:
            in_progress.append(entry)

    ports = []
    for pr in trailer_prs:
        for sha, verdict, reason in parse_trailers(pr.get("body")):
            oid = (pr.get("mergeCommit") or {}).get("oid")
            ports.append(
                {"sha": sha, "verdict": verdict, "reason": reason, "pr": pr["number"], "released_in": release_of(oid) if oid else None}
            )
    ports.sort(key=lambda p: (p["sha"], p["pr"]))

    return {
        "solved": solved,
        "in_progress": in_progress,
        "skipped": [dataclasses.asdict(s) for s in skips],
        "upstream_commits": ports,
    }


def _upstream_links(nums: list[int]) -> str:
    return ", ".join(f"[{UPSTREAM}#{n}](https://github.com/{UPSTREAM}/issues/{n})" for n in nums)


def render_solved_md(ledger: dict) -> str:
    out = [
        "# Upstream issues — solved / in progress / skipped",
        "",
        "_Generated by `scripts/upstream_ledger.py` — do not edit by hand._",
        "",
        f"## Solved ({len(ledger['solved'])})",
        "",
        "| Upstream | Fork issue | PR | Released in |",
        "|---|---|---|---|",
    ]
    for e in ledger["solved"]:
        pr = f"#{e['pr']}" if e["pr"] else "closed without linked PR"
        out.append(f"| {_upstream_links(e['upstream'])} | #{e['fork_issue']} | {pr} | {e['released_in'] or '—'} |")
    out += ["", f"## In progress ({len(ledger['in_progress'])})", "", "| Upstream | Fork issue | Pri |", "|---|---|---|"]
    for e in ledger["in_progress"]:
        out.append(f"| {_upstream_links(e['upstream'])} | #{e['fork_issue']} | {e['pri'] or '—'} |")
    out += ["", f"## Ported / skipped upstream commits ({len(ledger['upstream_commits'])})", "", "| Commit | Verdict | PR | Released in |", "|---|---|---|---|"]
    for p in ledger["upstream_commits"]:
        reason = f" — {p['reason']}" if p["reason"] else ""
        out.append(f"| `{p['sha'][:9]}` | {p['verdict']}{reason} | #{p['pr']} | {p['released_in'] or '—'} |")
    out += ["", f"## Skipped at triage ({len(ledger['skipped'])})", "", "| Upstream | Reason | Title |", "|---|---|---|"]
    for s in ledger["skipped"]:
        out.append(f"| {_upstream_links([s['upstream']])} | {s['reason']} | {s['title']} |")
    return "\n".join(out) + "\n"


def render_release_section(ledger: dict, tag: str) -> str:
    hits = [e for e in ledger["solved"] if e["released_in"] == tag]
    if not hits:
        return ""
    lines = ["### Upstream issues addressed", ""]
    for e in hits:
        title = f" — {e['title']}" if e["title"] else ""
        lines.append(f"- {_upstream_links(e['upstream'])} via #{e['fork_issue']} (PR #{e['pr']}){title}")
    return "\n".join(lines) + "\n"


class GitHubClient:
    """Thin gh-CLI wrapper. Everything network-y lives here so tests can fake it."""

    def __init__(self, repo: str = FORK_REPO) -> None:
        self.owner, self.name = repo.split("/")

    def _gh(self, *args: str) -> str:
        return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout

    def issue_states(self) -> dict[int, dict]:
        query = """query($owner:String!,$name:String!,$cursor:String){
          repository(owner:$owner,name:$name){
            issues(first:100,after:$cursor,states:[OPEN,CLOSED]){
              pageInfo{hasNextPage endCursor}
              nodes{number state body closedByPullRequestsReferences(first:5){nodes{number mergeCommit{oid}}}}}}}"""
        out: dict[int, dict] = {}
        cursor = None
        while True:
            args = ["api", "graphql", "-f", f"query={query}", "-f", f"owner={self.owner}", "-f", f"name={self.name}"]
            if cursor:
                args += ["-f", f"cursor={cursor}"]
            page = json.loads(self._gh(*args))["data"]["repository"]["issues"]
            for node in page["nodes"]:
                out[node["number"]] = node
            if not page["pageInfo"]["hasNextPage"]:
                return out
            cursor = page["pageInfo"]["endCursor"]

    def merged_trailer_prs(self) -> list[dict]:
        query = """query($q:String!){search(query:$q,type:ISSUE,first:100){
          nodes{... on PullRequest{number body mergeCommit{oid}}}}}"""
        q = f'repo:{self.owner}/{self.name} is:pr is:merged "Upstream-commit:" in:body'
        return json.loads(self._gh("api", "graphql", "-f", f"query={query}", "-f", f"q={q}"))["data"]["search"]["nodes"]


def first_release_containing(oid: str, repo_root: Path) -> str | None:
    res = subprocess.run(
        ["git", "-C", str(repo_root), "tag", "--contains", oid, "-l", "v*", "--sort=creatordate"],
        capture_output=True,
        text=True,
    )
    tags = res.stdout.split()
    return tags[0] if res.returncode == 0 and tags else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--release-notes", metavar="TAG")
    args = ap.parse_args(argv)

    repo_root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True).stdout.strip())
    out_dir = repo_root / "docs" / "upstream"

    if args.release_notes:
        ledger = json.loads((out_dir / "ledger.json").read_text())
        sys.stdout.write(render_release_section(ledger, args.release_notes))
        return 0

    rows, skips = parse_triage((repo_root / "docs" / "upstream-triage.md").read_text())
    client = GitHubClient()
    ledger = build_ledger(
        rows, skips, client.issue_states(), client.merged_trailer_prs(),
        release_of=lambda oid: first_release_containing(oid, repo_root),
    )
    md, js = render_solved_md(ledger), json.dumps(ledger, indent=2) + "\n"
    if args.check:
        current = (out_dir / "SOLVED.md").read_text() if (out_dir / "SOLVED.md").exists() else ""
        if current != md:
            sys.stderr.write("ledger out of date — run: python3 scripts/upstream_ledger.py --write\n")
            return 1
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "SOLVED.md").write_text(md)
    (out_dir / "ledger.json").write_text(js)
    print(f"wrote {out_dir / 'SOLVED.md'} ({len(ledger['solved'])} solved, {len(ledger['in_progress'])} in progress)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_upstream_ledger.py -v
```

Expected: all pass (5 tests).

- [ ] **Step 5: Generate the real ledger and sanity-check**

```bash
python3 scripts/upstream_ledger.py --write
python3 scripts/upstream_ledger.py --check && echo CHECK-OK
grep -c "^| \[" docs/upstream/SOLVED.md || true
head -20 docs/upstream/SOLVED.md
```

Expected: `--write` prints a solved count ≥ 60 (the July sweep closed most sweep issues); `CHECK-OK`; SOLVED.md has the four sections. Spot-check: upstream #217 must appear under **In progress** (fork #56 is open).

- [ ] **Step 6: Commit**

```bash
git add scripts/upstream_ledger.py tests/test_upstream_ledger.py docs/upstream/
git commit -m "feat(ledger): live join + SOLVED.md/ledger.json renderers and CLI"
```

---

### Task 4: Ledger workflow + release-notes categories

**Repo:** `/home/sam/spoolman/Spoolman`, branch `feat/process-layer`

**Files:**
- Create: `.github/workflows/ledger.yml`
- Create: `.github/release.yml`

**Interfaces:**
- Consumes: `scripts/upstream_ledger.py --write` / `--release-notes TAG` (Task 3).

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/ledger.yml`:

```yaml
name: Upstream ledger

on:
  release:
    types: [published]
  schedule:
    - cron: "30 5 * * 1" # Mondays 05:30 UTC, after the upstream watch
  workflow_dispatch:

permissions:
  contents: write

jobs:
  regenerate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          ref: master
          fetch-depth: 0 # ledger maps merge commits to release tags

      - name: Regenerate ledger
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python3 scripts/upstream_ledger.py --write

      - name: Commit if changed
        run: |
          if git diff --quiet -- docs/upstream; then
            echo "ledger unchanged"
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add docs/upstream
          git commit -m "docs: regenerate upstream ledger [skip ci]"
          git push origin master

      - name: Append upstream section to the release notes
        if: github.event_name == 'release'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TAG: ${{ github.event.release.tag_name }}
        run: |
          python3 scripts/upstream_ledger.py --release-notes "${TAG}" > /tmp/section.md
          if [ ! -s /tmp/section.md ]; then
            echo "no upstream issues in ${TAG}"
            exit 0
          fi
          gh release view "${TAG}" --json body --jq .body > /tmp/body.md
          if grep -q "### Upstream issues addressed" /tmp/body.md; then
            echo "section already present"
            exit 0
          fi
          printf '\n' >> /tmp/body.md
          cat /tmp/section.md >> /tmp/body.md
          gh release edit "${TAG}" --notes-file /tmp/body.md
```

- [ ] **Step 2: Write the release-notes categories**

Create `.github/release.yml`:

```yaml
changelog:
  exclude:
    labels:
      - upstream-watch
  categories:
    - title: Fixes
      labels: [bug]
    - title: Features
      labels: [enhancement]
    - title: Documentation
      labels: [documentation]
    - title: Other changes
      labels: ["*"]
```

- [ ] **Step 3: Validate YAML and commit**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ledger.yml')); yaml.safe_load(open('.github/release.yml')); print('OK')"
git add .github/workflows/ledger.yml .github/release.yml
git commit -m "ci: ledger regeneration workflow + release-notes categories"
```

(Live verification happens in Task 9 after merge, via `workflow_dispatch`.)

---

### Task 5: Upstream watch — script (TDD) + workflow + seed state

**Repo:** `/home/sam/spoolman/Spoolman`, branch `feat/process-layer`

**Files:**
- Create: `scripts/upstream_watch.py`
- Test: `tests/test_upstream_watch.py`
- Create: `docs/upstream/watch-state.json` (seed)
- Create: `.github/workflows/upstream-watch.yml`

**Interfaces:**
- Produces:
  - `render_watch_issue(commits: list[dict], issues: list[dict], prs: list[dict]) -> str | None` — `commits`: `{sha, subject, dirs: list[str]}`; `issues`/`prs`: `{number, title, created_at}`. Returns `None` when all lists are empty.
  - `filter_created_after(items: list[dict], watermark: str) -> list[dict]` — ISO-8601 string comparison.
  - CLI: `python3 scripts/upstream_watch.py --state <path> --out <path>`; expects `FETCH_HEAD` = upstream master; writes `has_news=true|false` to `$GITHUB_OUTPUT` if set; updates the state file in place.
- **Constraint (spec decision 2):** the generated body backticks every upstream reference — zero cross-links from listings.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_upstream_watch.py`:

```python
"""Tests for scripts/upstream_watch.py (pure functions only)."""
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from upstream_watch import filter_created_after, render_watch_issue  # noqa: E402


def test_render_empty_is_none() -> None:
    assert render_watch_issue([], [], []) is None


def test_render_body_backticks_refs_and_lists_all() -> None:
    commits = [{"sha": "a" * 40, "subject": "Fix theme", "dirs": ["client", "spoolman"]}]
    issues = [{"number": 970, "title": "New issue", "created_at": "2026-07-12T10:00:00Z"}]
    prs = [{"number": 971, "title": "New PR", "created_at": "2026-07-13T10:00:00Z"}]
    body = render_watch_issue(commits, issues, prs)
    assert "### New upstream commits (1)" in body
    assert f"- [ ] `{'a' * 9}` Fix theme (`client`, `spoolman`) — port / skip?" in body
    assert "`Donkie/Spoolman#970`" in body and "`Donkie/Spoolman#971`" in body
    # zero un-backticked upstream refs (no cross-link spam from listings):
    assert "Donkie/Spoolman#" not in body.replace("`Donkie/Spoolman#", "")
    assert "github.com/Donkie" not in body


def test_filter_created_after() -> None:
    items = [
        {"number": 1, "created_at": "2026-07-05T00:00:00Z"},
        {"number": 2, "created_at": "2026-07-07T00:00:00Z"},
    ]
    assert [i["number"] for i in filter_created_after(items, "2026-07-06T00:00:00Z")] == [2]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_upstream_watch.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'upstream_watch'`

- [ ] **Step 3: Implement**

Create `scripts/upstream_watch.py`:

```python
"""Weekly upstream watch: report new Donkie/Spoolman commits/issues/PRs since the watermark.

Design: docs/superpowers/specs/2026-07-15-org-process-layer-design.md (section B).
IMPORTANT: generated bodies must backtick upstream refs — listings must not cross-link upstream.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

UPSTREAM = "Donkie/Spoolman"


def filter_created_after(items: list[dict], watermark: str) -> list[dict]:
    return [i for i in items if i["created_at"] > watermark]


def render_watch_issue(commits: list[dict], issues: list[dict], prs: list[dict]) -> str | None:
    if not (commits or issues or prs):
        return None
    out = [
        "Weekly upstream watch. Check items off as they are triaged; record port verdicts in the",
        "porting PRs via `Upstream-commit: <sha> ported|skipped — reason` trailers.",
        "(Upstream refs are backticked on purpose — listings must not cross-link upstream.)",
        "",
    ]
    if commits:
        out += [f"### New upstream commits ({len(commits)})", ""]
        for c in commits:
            dirs = ", ".join(f"`{d}`" for d in c["dirs"]) or "`.`"
            out.append(f"- [ ] `{c['sha'][:9]}` {c['subject']} ({dirs}) — port / skip?")
        out.append("")
    if issues:
        out += [f"### New upstream issues ({len(issues)})", ""]
        out += [f"- [ ] `{UPSTREAM}#{i['number']}` {i['title']} — fix / implement / skip?" for i in issues]
        out.append("")
    if prs:
        out += [f"### New upstream PRs ({len(prs)})", ""]
        out += [f"- [ ] `{UPSTREAM}#{p['number']}` {p['title']} — mine / ignore?" for p in prs]
        out.append("")
    return "\n".join(out)


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo_root), *args], check=True, capture_output=True, text=True).stdout


def new_commits(repo_root: Path, since_sha: str) -> list[dict]:
    log = _git(repo_root, "log", "--reverse", "--format=%H%x09%s", f"{since_sha}..FETCH_HEAD")
    commits = []
    for line in log.splitlines():
        sha, subject = line.split("\t", 1)
        names = _git(repo_root, "show", "--pretty=format:", "--name-only", sha)
        dirs = sorted({n.split("/", 1)[0] for n in names.splitlines() if n})
        commits.append({"sha": sha, "subject": subject, "dirs": dirs})
    return commits


def new_issues_and_prs(since: str) -> tuple[list[dict], list[dict]]:
    raw = subprocess.run(
        ["gh", "api", f"repos/{UPSTREAM}/issues?state=all&sort=created&direction=desc&per_page=100&since={since}", "--paginate"],
        check=True, capture_output=True, text=True,
    ).stdout
    # --paginate concatenates JSON arrays; normalise before parsing.
    items = json.loads("[" + raw.replace("][", ",").strip("[]") + "]") if raw.strip() else []
    issues = [{"number": i["number"], "title": i["title"], "created_at": i["created_at"]} for i in items if "pull_request" not in i]
    prs = [{"number": i["number"], "title": i["title"], "created_at": i["created_at"]} for i in items if "pull_request" in i]
    return issues, prs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)

    repo_root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True).stdout.strip())
    state = json.loads(args.state.read_text())

    commits = new_commits(repo_root, state["last_commit_sha"])
    issues_all, prs_all = new_issues_and_prs(min(state["last_issue_seen_at"], state["last_pr_seen_at"]))
    issues = filter_created_after(issues_all, state["last_issue_seen_at"])
    prs = filter_created_after(prs_all, state["last_pr_seen_at"])

    body = render_watch_issue(commits, issues, prs)
    has_news = body is not None
    if has_news:
        args.out.write_text(body)

    if commits:
        state["last_commit_sha"] = commits[-1]["sha"]
    if issues:
        state["last_issue_seen_at"] = max(i["created_at"] for i in issues)
    if prs:
        state["last_pr_seen_at"] = max(p["created_at"] for p in prs)
    args.state.write_text(json.dumps(state, indent=2) + "\n")

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as fh:
            fh.write(f"has_news={'true' if has_news else 'false'}\n")
    print(f"has_news={has_news} commits={len(commits)} issues={len(issues)} prs={len(prs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_upstream_watch.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Seed the watermark (merge-base ⇒ first run generates the 27-commit catch-up)**

```bash
git fetch https://github.com/Donkie/Spoolman.git master
MB=$(git merge-base master FETCH_HEAD)
printf '{\n  "last_commit_sha": "%s",\n  "last_issue_seen_at": "2026-07-06T00:00:00Z",\n  "last_pr_seen_at": "2026-07-06T00:00:00Z"\n}\n' "$MB" > docs/upstream/watch-state.json
cat docs/upstream/watch-state.json
```

(Issue/PR watermarks seed at the sweep date 2026-07-06 — everything upstream filed since the sweep shows up in run #1.)

- [ ] **Step 6: Dry-run the script locally against the real upstream**

```bash
python3 scripts/upstream_watch.py --state docs/upstream/watch-state.json --out /tmp/watch-preview.md
head -40 /tmp/watch-preview.md
git checkout docs/upstream/watch-state.json   # restore the seed — the real advance happens in CI
```

Expected: `has_news=True commits=27 ...` (±few if upstream moved); preview lists the known upstream commits (e.g. custom-field filtering #773, System theme). All refs backticked.

- [ ] **Step 7: Write the workflow**

Create `.github/workflows/upstream-watch.yml`:

```yaml
name: Upstream watch

on:
  schedule:
    - cron: "0 5 * * 1" # Mondays 05:00 UTC, after the 04:00 mutation run
  workflow_dispatch:

permissions:
  contents: write
  issues: write

jobs:
  watch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          ref: master
          fetch-depth: 0

      - name: Fetch upstream master
        run: git fetch https://github.com/Donkie/Spoolman.git master

      - name: Generate report and advance watermark
        id: gen
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python3 scripts/upstream_watch.py --state docs/upstream/watch-state.json --out /tmp/watch-issue.md

      - name: File the weekly watch issue
        if: steps.gen.outputs.has_news == 'true'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh issue create --repo "${GITHUB_REPOSITORY}" \
            --title "Upstream watch $(date -u +%G-W%V)" \
            --label upstream-watch \
            --body-file /tmp/watch-issue.md

      - name: Commit the watermark
        run: |
          if git diff --quiet -- docs/upstream/watch-state.json; then
            echo "watermark unchanged"
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add docs/upstream/watch-state.json
          git commit -m "chore: advance upstream watch watermark [skip ci]"
          git push origin master
```

- [ ] **Step 8: Create the label (idempotent) and commit**

```bash
gh label create upstream-watch --repo sherrmann/Spoolman-NG --description "Weekly upstream watch report" --color 5319e7 || true
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/upstream-watch.yml')); print('OK')"
git add scripts/upstream_watch.py tests/test_upstream_watch.py docs/upstream/watch-state.json .github/workflows/upstream-watch.yml
git commit -m "feat(watch): weekly upstream watch script, seeded watermark, workflow"
```

---

### Task 6: Add-on version bump becomes a PR + branch protection

**Repo:** `/home/sam/spoolman/Spoolman`, branch `feat/process-layer` (edits `ci.yml`), plus `gh api` settings on the add-ons repo.

**Files:**
- Modify: `.github/workflows/ci.yml:795-830` (the `sync-ha-addon` job's last step)

**Interfaces:**
- Consumes: check names `lint`, `build-smoke` from Task 1 (as required contexts).

- [ ] **Step 1: Enable auto-merge + branch protection on the add-ons repo**

```bash
gh api -X PATCH repos/sherrmann/spoolman-ng-addons -F allow_auto_merge=true -F delete_branch_on_merge=true --jq '{allow_auto_merge, delete_branch_on_merge}'
cat > /tmp/protection.json <<'JSON'
{
  "required_status_checks": {"strict": false, "contexts": ["lint", "build-smoke"]},
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON
gh api -X PUT repos/sherrmann/spoolman-ng-addons/branches/master/protection --input /tmp/protection.json --jq '.required_status_checks.contexts'
```

Expected: `["lint","build-smoke"]`. `enforce_admins: false` keeps owner pushes working during the transition.

- [ ] **Step 2: Rewrite the sync job's push as branch + PR + auto-merge**

In `.github/workflows/ci.yml`, inside the `sync-ha-addon` job's `Bump add-on to this release` step, replace the final block:

```yaml
          if git diff --quiet; then
            echo "Add-on already at ${ver}; nothing to push."
            exit 0
          fi
          git config user.name "${GITHUB_ACTOR}"
          git config user.email "${GITHUB_ACTOR_ID}+${GITHUB_ACTOR}@users.noreply.github.com"
          git commit -am "Bump Spoolman NG add-on to ${ver}"
          git push
```

with:

```yaml
          if git diff --quiet; then
            echo "Add-on already at ${ver}; nothing to push."
            exit 0
          fi
          git config user.name "${GITHUB_ACTOR}"
          git config user.email "${GITHUB_ACTOR_ID}+${GITHUB_ACTOR}@users.noreply.github.com"
          branch="release-bump/${ver}"
          git checkout -b "${branch}"
          git commit -am "Bump Spoolman NG add-on to ${ver}"
          git push origin "${branch}"
          gh pr create --repo sherrmann/spoolman-ng-addons --head "${branch}" \
            --title "Bump Spoolman NG add-on to ${ver}" \
            --body "Automated release bump. Server changes: https://github.com/sherrmann/Spoolman-NG/releases/tag/v${ver}"
          gh pr merge --repo sherrmann/spoolman-ng-addons "${branch}" --auto --squash
        env:
          GH_TOKEN: ${{ secrets.PAT }}
```

(The `env:` goes on the step, same indentation as its `run:`. PAT-created PRs DO trigger the add-ons CI — the GITHUB_TOKEN no-trigger rule doesn't apply to PATs.)

- [ ] **Step 3: Validate and commit**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('OK')"
git add .github/workflows/ci.yml
git commit -m "ci: add-on release bump goes through an auto-merge PR gated by add-on CI"
```

- [ ] **Step 4: Prove the auto-merge path with a throwaway PR in the add-ons repo**

```bash
cd /home/sam/spoolman-ng-addons
git checkout -b test/automerge && git commit --allow-empty -m "test: verify auto-merge waits for required checks"
git push origin test/automerge
gh pr create --title "test: auto-merge verification" --body "Throwaway — verifies required checks gate auto-merge." --head test/automerge
gh pr merge test/automerge --auto --squash
sleep 90 && gh pr view test/automerge --json state,mergedAt --jq '{state, mergedAt}'
git checkout master && git pull --ff-only
cd /home/sam/spoolman/Spoolman
```

Expected: state `MERGED` with a timestamp *after* the CI run finished (auto-merge waited for `lint`/`build-smoke`). The full release path is verified live at the next real release — note this in the PR description in Task 9.

---

### Task 7: SpoolmanDB upstream auto-sync

**Repo:** `/home/sam/SpoolmanDB` (branch `main`, direct push — do settings *after* the workflow lands)

**Files:**
- Create: `.github/workflows/upstream-sync.yml`
- Modify: `.github/workflows/build.yml` (add `upstream-sync/**` to push branches)
- Also: delete the stale `patch-1` remote branch.

**Interfaces:**
- Consumes: build.yml job names `validate` and `compile` (verified in repo) as required contexts.

- [ ] **Step 1: Extend build.yml triggers**

In `.github/workflows/build.yml`, the `on.push.branches` list currently contains only the main branch. Add the sync branch pattern so check runs report on sync-branch SHAs (required because auto-merge needs the contexts on the PR head; a push-triggered run satisfies them):

```yaml
on:
  push:
    branches:
      - main
      - "upstream-sync/**"
```

(Keep the existing `pull_request` and `workflow_dispatch` triggers unchanged. Check the `deploy` job: if it is gated on `github.ref == 'refs/heads/main'` it stays safe; if it has no ref condition, add `if: github.ref == 'refs/heads/main'` to it so sync branches never deploy Pages.)

- [ ] **Step 2: Write the sync workflow**

Create `.github/workflows/upstream-sync.yml`:

```yaml
name: Upstream sync

on:
  schedule:
    - cron: "0 6 * * 1" # Mondays 06:00 UTC
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0

      - name: Fetch upstream
        run: git fetch https://github.com/Donkie/SpoolmanDB.git main

      - name: Count new upstream commits
        id: check
        run: echo "count=$(git rev-list --count main..FETCH_HEAD)" >> "$GITHUB_OUTPUT"

      - name: Merge and open auto-merge PR (or conflict issue)
        if: steps.check.outputs.count != '0'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          COUNT: ${{ steps.check.outputs.count }}
        run: |
          week=$(date -u +%G-W%V)
          branch="upstream-sync/${week}"
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git checkout -b "${branch}"
          if git merge --no-edit FETCH_HEAD; then
            git push origin "${branch}"
            gh pr create --head "${branch}" \
              --title "Upstream sync ${week} (${COUNT} commits)" \
              --body "Automated weekly merge of Donkie/SpoolmanDB main. Schema/build CI is the gate."
            gh pr merge "${branch}" --auto --merge
          else
            files=$(git diff --name-only --diff-filter=U | sed 's/^/- /')
            git merge --abort
            gh issue create --title "Upstream sync conflict ${week}" \
              --label upstream-sync-conflict \
              --body "$(printf 'Weekly merge of Donkie/SpoolmanDB main hit conflicts in:\n\n%s\n\nResolve manually: fetch upstream, merge, push a PR.' "${files}")"
          fi
```

Note the GITHUB_TOKEN trap: events created with `GITHUB_TOKEN` — **including branch pushes, not just PR creation** — don't trigger workflows, so neither the push trigger nor `pull_request` fires and auto-merge would hang. `workflow_dispatch` is documented as exempt from this rule, so the sync job must explicitly `gh workflow run build.yml --ref "${branch}"` after pushing (needs `actions: write`); the resulting check runs attach to the branch head SHA and satisfy the required contexts. (CORRECTED DURING EXECUTION — the original plan text wrongly claimed a push-triggered run would fire; caught by the Task 7 review. The `upstream-sync/**` push trigger stays: it's what makes the dispatched run's checks land, and covers manually-pushed sync branches.)

- [ ] **Step 3: Enable issues, auto-merge, protection, label; drop stale branch**

```bash
cd /home/sam/SpoolmanDB
gh api -X PATCH repos/sherrmann/SpoolmanDB -F has_issues=true -F allow_auto_merge=true -F delete_branch_on_merge=true --jq '{has_issues, allow_auto_merge}'
gh label create upstream-sync-conflict --repo sherrmann/SpoolmanDB --description "Weekly upstream merge hit conflicts" --color d93f0b || true
cat > /tmp/db-protection.json <<'JSON'
{
  "required_status_checks": {"strict": false, "contexts": ["validate", "compile"]},
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON
gh api -X PUT repos/sherrmann/SpoolmanDB/branches/main/protection --input /tmp/db-protection.json --jq '.required_status_checks.contexts'
git push origin --delete patch-1
```

Expected: `has_issues: true`, contexts `["validate","compile"]`, `patch-1` deleted (verified superseded — content already in main as `40eaade`).

Important: verify the exact check names first — `gh api repos/sherrmann/SpoolmanDB/commits/main/check-runs --jq '.check_runs[].name'`. If they print as something other than `validate`/`compile`, use the printed names in the protection contexts.

- [ ] **Step 4: Commit, push, verify the no-op path**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/upstream-sync.yml')); yaml.safe_load(open('.github/workflows/build.yml')); print('OK')"
git add .github/workflows/
git commit -m "ci: weekly upstream auto-sync (auto-merge PR, conflict fallback issue)"
git push origin main
gh workflow run upstream-sync.yml --repo sherrmann/SpoolmanDB
sleep 45 && gh run list --repo sherrmann/SpoolmanDB --workflow upstream-sync.yml --limit 1
```

Expected: run green with `count=0` → no PR (upstream has been idle since 2025-11-28, and the fork is 0 behind). The merge/conflict paths execute on the first real upstream movement; both were desk-checked here.

(Note: push to protected `main` still works — `enforce_admins` is false and you're the repo admin.)

---

### Task 8: Contribution conventions

**Repo:** `/home/sam/spoolman/Spoolman`, branch `feat/process-layer`

**Files:**
- Modify: `CONTRIBUTING.md` (append a section)

- [ ] **Step 1: Append the conventions section**

Append to `CONTRIBUTING.md`:

```markdown

## Upstream references

When a change addresses an upstream issue, add a plain-text line to the PR or issue body:

    Upstream: https://github.com/Donkie/Spoolman/issues/NNN

Written **unbackticked**, so GitHub cross-links it quietly upstream and `scripts/upstream_ledger.py`
picks it up for `docs/upstream/SOLVED.md`.

When a PR ports (or deliberately skips) upstream commits, add one trailer line per commit:

    Upstream-commit: <sha> ported
    Upstream-commit: <sha> skipped — <short reason>

Exception: **generated** listings (the weekly `upstream-watch` issues) backtick upstream refs on
purpose — bulk listings must not cross-link 100 upstream threads. Only real work items link.
```

- [ ] **Step 2: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: upstream reference + port-trailer conventions"
```

---

### Task 9: Main-repo PR, merge, live verification

**Repo:** `/home/sam/spoolman/Spoolman`, branch `feat/process-layer`

- [ ] **Step 1: Full local test suite**

```bash
uv run pytest tests/test_upstream_ledger.py tests/test_upstream_watch.py -v
python3 scripts/upstream_ledger.py --check && echo CHECK-OK
```

Expected: all pass, `CHECK-OK`.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin feat/process-layer
gh pr create --title "Process layer: upstream ledger + weekly watch, add-on bump via PR, conventions" --body "$(cat <<'EOF'
Implements docs/superpowers/specs/2026-07-15-org-process-layer-design.md (sections A, B, C2, C5 + conventions; the add-ons CI and SpoolmanDB sync live in their own repos).

- `scripts/upstream_ledger.py` + `ledger.yml`: docs/upstream/SOLVED.md + ledger.json regenerated on release/weekly; release notes gain an "Upstream issues addressed" section.
- `scripts/upstream_watch.py` + `upstream-watch.yml`: weekly upstream commit/issue/PR report as a checklist issue; watermark seeded at the merge-base, so run #1 files the 27-commit catch-up.
- `sync-ha-addon` now opens an auto-merge PR gated by the new add-ons CI instead of pushing master (deferred live check: fires on the next release).
- CONTRIBUTING: unbackticked `Upstream:` links + `Upstream-commit:` trailers; generated listings stay backticked.

Includes the spec + plan docs.
EOF
)"
gh pr checks --watch
```

Expected: all CI checks green. Merge with the repo's usual flow (`gh pr merge --squash --delete-branch`), then `git checkout master && git pull --ff-only`.

- [ ] **Step 3: Live-verify both workflows on master**

```bash
gh workflow run ledger.yml --repo sherrmann/Spoolman-NG
gh workflow run upstream-watch.yml --repo sherrmann/Spoolman-NG
sleep 90
gh run list --repo sherrmann/Spoolman-NG --workflow ledger.yml --limit 1
gh run list --repo sherrmann/Spoolman-NG --workflow upstream-watch.yml --limit 1
gh issue list --repo sherrmann/Spoolman-NG --label upstream-watch
```

Expected: both runs green; one new `Upstream watch 2026-W29` issue containing the ~27-commit catch-up checklist plus upstream issues/PRs since 2026-07-06; a bot commit `chore: advance upstream watch watermark [skip ci]` on master. Pull master and confirm `docs/upstream/watch-state.json` advanced.

---

### Task 10: Org trial runbook (MANUAL — with the maintainer, gated)

**No repo changes.** This is spec section D Phase 0, steps 1–3 only. The pilot transfer (step 4) and everything beyond run **only after** the maintainer reviews the findings and picks the real org name.

- [ ] **Step 1 (maintainer, browser):** create a throwaway org — https://github.com/account/organizations/new → Free plan → name `spoolman-ng-trial`. Org creation has no API on free plans; this is a UI step.

- [ ] **Step 2: scratch repo exercising Actions + ghcr + Pages**

```bash
gh repo create spoolman-ng-trial/actions-trial --public --add-readme
gh api /orgs/spoolman-ng-trial --jq '.plan | {name, private_repos}'
```

Expected plan name: `free`. Then clone and push this workflow:

```bash
cd /home/sam/.claude/jobs/d5ad984c/tmp 2>/dev/null || cd /tmp
gh repo clone spoolman-ng-trial/actions-trial && cd actions-trial
mkdir -p .github/workflows
# write the YAML below to .github/workflows/trial.yml, then:
git add .github && git commit -m "trial workflow" && git push
```

`.github/workflows/trial.yml`:

```yaml
name: trial
on:
  push:
  schedule:
    - cron: "*/30 * * * *"
  workflow_dispatch:
permissions:
  contents: read
  packages: write
jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - run: echo "actions run fine in the org"
      - name: Push a ghcr package under the org namespace
        run: |
          echo "FROM alpine:3.20" > Dockerfile.trial
          echo '${{ secrets.GITHUB_TOKEN }}' | docker login ghcr.io -u "${{ github.actor }}" --password-stdin
          docker build -f Dockerfile.trial -t ghcr.io/spoolman-ng-trial/actions-trial:trial .
          docker push ghcr.io/spoolman-ng-trial/actions-trial:trial
```

- [ ] **Step 3: verify the trial checklist**

```bash
gh run list --repo spoolman-ng-trial/actions-trial --limit 5          # push + schedule runs, conclusion success
docker pull ghcr.io/spoolman-ng-trial/actions-trial:trial              # after making the package public in org package settings
```

Plus (maintainer, browser): org Settings → Billing — expect Free plan, $0, public-repo Actions/Packages usage not metered. Record all findings as comments in a checklist issue or directly in the spec doc.

- [ ] **Step 4: REVIEW GATE — stop.** Present findings to the maintainer; they decide the real org name and green-light spec Phase 0 step 4 (pilot transfer of `spoolman-ng-addons` via `gh api -X POST repos/sherrmann/spoolman-ng-addons/transfer -f new_owner=<real-org>`) and Phases 1–2. Delete the trial org afterwards (browser: org Settings → Delete).

---

## Execution notes

- Task order matters only where stated: 1 → 6 (check names → protection), 2 → 3 → 4/5 (module builds up), 9 last for the main repo. Task 7 is fully independent; Task 10 is manual and last.
- If upstream moves between Task 5's dry run and Task 9's live run, commit/issue counts shift — that's expected; assertions on exact counts live only in tests against the frozen triage doc.
- Nothing here touches `secrets.PAT`, release tagging, or the mobile pipeline.
- **Documented deviation from the spec:** `upstream_ledger.py --check` is NOT wired into per-PR CI. It regenerates from live GitHub state (network + token), which would make PR checks slow and flaky. Staleness is covered by the weekly + on-release regeneration in `ledger.yml`; `--check` remains a local/manual tool (used in Tasks 3 and 9).
- **Final-review fix:** `ledger.yml`'s `release: types: [published]` trigger got the same GITHUB_TOKEN-dispatch treatment as Task 7's `build.yml` (see the note above at line 1178) — the release created by `ci.yml`'s `publish-release` job uses `GITHUB_TOKEN`, so it never fires that trigger. `ci.yml` now dispatches `ledger.yml` explicitly (`gh workflow run ledger.yml --ref master -f tag="${GITHUB_REF_NAME}"`, needing `actions: write` on that job) right after creating the release; the `release:` trigger stays in `ledger.yml` too, covering releases published manually through the GitHub UI.
