"""Regenerate docs/upstream/SOLVED.md + ledger.json from the triage doc and live GitHub state.

Design: docs/superpowers/specs/2026-07-15-org-process-layer-design.md (section A).
Stdlib-only; external I/O goes through `git` and `gh` subprocesses (GitHubClient below).
"""

# ruff: noqa: T201, S607

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

FORK_REPO = "sherrmann/Spoolman-NG"
UPSTREAM = "Donkie/Spoolman"


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


_REF_LINE = re.compile(r"^\s*\**Upstream:?\**", re.IGNORECASE)
_REF = re.compile(r"Donkie/Spoolman(?:#|/issues/)(\d+)")
_TRAILER = re.compile(
    r"Upstream-commit:\s*([0-9a-f]{7,40})\s+(ported|skipped)(?:\s*[—–-]\s*(\S.*?))?\s*$",  # noqa: RUF001
    re.IGNORECASE | re.MULTILINE,
)


def upstream_refs_from_body(body: str | None) -> list[int]:
    """Extract upstream Donkie/Spoolman issue numbers from lines starting with 'Upstream:'."""
    refs: list[int] = []
    for line in (body or "").splitlines():
        if _REF_LINE.match(line):
            refs += [int(n) for n in _REF.findall(line)]
    return refs


def parse_trailers(body: str | None) -> list[tuple[str, str, str]]:
    """Extract (sha, verdict, reason) from 'Upstream-commit:' trailers in a PR body."""
    return [(sha, verdict.lower(), (reason or "").strip()) for sha, verdict, reason in _TRAILER.findall(body or "")]


def build_ledger(
    rows: list[TriageRow],
    skips: list[SkipRow],
    issue_states: dict[int, dict],
    trailer_prs: list[dict],
    release_of: Callable[[str], str | None],
) -> dict:
    """Join triage rows/skips with live issue state and merged trailer PRs into a ledger dict."""
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
            has_merge_commit = prs and prs[0].get("mergeCommit")
            entry["released_in"] = release_of(prs[0]["mergeCommit"]["oid"]) if has_merge_commit else None
            solved.append(entry)
        else:
            in_progress.append(entry)

    ports = []
    for pr in trailer_prs:
        for sha, verdict, reason in parse_trailers(pr.get("body")):
            oid = (pr.get("mergeCommit") or {}).get("oid")
            ports.append(
                {
                    "sha": sha,
                    "verdict": verdict,
                    "reason": reason,
                    "pr": pr["number"],
                    "released_in": release_of(oid) if oid else None,
                }
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
    """Render the four-section Markdown ledger (solved / in progress / ports / skipped)."""
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
    out += [
        "",
        f"## In progress ({len(ledger['in_progress'])})",
        "",
        "| Upstream | Fork issue | Pri |",
        "|---|---|---|",
    ]
    for e in ledger["in_progress"]:
        out.append(f"| {_upstream_links(e['upstream'])} | #{e['fork_issue']} | {e['pri'] or '—'} |")
    out += [
        "",
        f"## Ported / skipped upstream commits ({len(ledger['upstream_commits'])})",
        "",
        "| Commit | Verdict | PR | Released in |",
        "|---|---|---|---|",
    ]
    for p in ledger["upstream_commits"]:
        reason = f" — {p['reason']}" if p["reason"] else ""
        out.append(f"| `{p['sha'][:9]}` | {p['verdict']}{reason} | #{p['pr']} | {p['released_in'] or '—'} |")
    out += [
        "",
        f"## Skipped at triage ({len(ledger['skipped'])})",
        "",
        "| Upstream | Reason | Title |",
        "|---|---|---|",
    ]
    for s in ledger["skipped"]:
        out.append(f"| {_upstream_links([s['upstream']])} | {s['reason']} | {s['title']} |")
    return "\n".join(out) + "\n"


def render_release_section(ledger: dict, tag: str) -> str:
    """Render the '### Upstream issues addressed' release-notes snippet for one released tag."""
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
        """Split repo (e.g. 'owner/name') into owner/name for use in gh API calls."""
        self.owner, self.name = repo.split("/")

    def _gh(self, *args: str) -> str:
        return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout

    def issue_states(self) -> dict[int, dict]:
        """Fetch every fork issue's number/state/body/closing-PR via paginated GraphQL."""
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
        """Search merged fork PRs whose body contains an 'Upstream-commit:' trailer."""
        query = """query($q:String!,$cursor:String){search(query:$q,type:ISSUE,first:100,after:$cursor){
          pageInfo{hasNextPage endCursor}
          nodes{... on PullRequest{number body mergeCommit{oid}}}}}"""
        q = f'repo:{self.owner}/{self.name} is:pr is:merged "Upstream-commit:" in:body'
        out: list[dict] = []
        cursor = None
        while True:
            args = ["api", "graphql", "-f", f"query={query}", "-f", f"q={q}"]
            if cursor:
                args += ["-f", f"cursor={cursor}"]
            page = json.loads(self._gh(*args))["data"]["search"]
            out += page["nodes"]
            if not page["pageInfo"]["hasNextPage"]:
                return out
            cursor = page["pageInfo"]["endCursor"]


def first_release_containing(oid: str, repo_root: Path) -> str | None:
    """Return the earliest v* tag containing commit `oid`, or None if untagged/unknown."""
    res = subprocess.run(
        ["git", "-C", str(repo_root), "tag", "--contains", oid, "-l", "v*", "--sort=creatordate"],
        capture_output=True,
        text=True,
        check=False,
    )
    tags = res.stdout.split()
    return tags[0] if res.returncode == 0 and tags else None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: --write regenerates the ledger, --check verifies it, --release-notes TAG prints a snippet."""
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--release-notes", metavar="TAG")
    args = ap.parse_args(argv)

    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True)
    repo_root = Path(root.stdout.strip())
    out_dir = repo_root / "docs" / "upstream"

    if args.release_notes:
        ledger = json.loads((out_dir / "ledger.json").read_text())
        sys.stdout.write(render_release_section(ledger, args.release_notes))
        return 0

    rows, skips = parse_triage((repo_root / "docs" / "upstream-triage.md").read_text())
    client = GitHubClient()
    ledger = build_ledger(
        rows,
        skips,
        client.issue_states(),
        client.merged_trailer_prs(),
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
