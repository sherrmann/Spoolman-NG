"""Weekly upstream watch: report new Donkie/Spoolman commits/issues/PRs since the watermark.

Design: docs/superpowers/specs/2026-07-15-org-process-layer-design.md (section B).
IMPORTANT: generated bodies must backtick upstream refs — listings must not cross-link upstream.
"""

# ruff: noqa: T201, S607

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

UPSTREAM = "Donkie/Spoolman"


def filter_created_after(items: list[dict], watermark: str) -> list[dict]:
    """Keep only items whose ISO-8601 `created_at` sorts strictly after `watermark`."""
    return [i for i in items if i["created_at"] > watermark]


def render_watch_issue(commits: list[dict], issues: list[dict], prs: list[dict]) -> str | None:
    """Render the weekly watch issue body, or None when there is nothing to report."""
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
            # Subject is backticked too: "(#N)" in upstream subjects must not auto-link against our repo.
            out.append(f"- [ ] `{c['sha'][:9]}` `{c['subject']}` ({dirs}) — port / skip?")
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
    """List commits on FETCH_HEAD since `since_sha`, each with the top-level dirs it touched."""
    log = _git(repo_root, "log", "--reverse", "--format=%H%x09%s", f"{since_sha}..FETCH_HEAD")
    commits = []
    for line in log.splitlines():
        sha, subject = line.split("\t", 1)
        names = _git(repo_root, "show", "--pretty=format:", "--name-only", sha)
        dirs = sorted({n.split("/", 1)[0] for n in names.splitlines() if n})
        commits.append({"sha": sha, "subject": subject, "dirs": dirs})
    return commits


def new_issues_and_prs(since: str) -> tuple[list[dict], list[dict]]:
    """Fetch upstream issues/PRs created since `since`, split into (issues, prs)."""
    raw = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{UPSTREAM}/issues?state=all&sort=created&direction=desc&per_page=100&since={since}",
            "--paginate",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    # --paginate concatenates JSON arrays ("[…][…]"); decode them as a stream —
    # string splicing would crash on an empty page ("[]"). (gh's --slurp flag
    # would do this for us, but needs gh >= 2.47; this works on any version.)
    decoder = json.JSONDecoder()
    items: list[dict] = []
    idx, end = 0, len(raw)
    while idx < end:
        page, idx = decoder.raw_decode(raw, idx)
        items.extend(page)
        while idx < end and raw[idx] in " \t\r\n":
            idx += 1

    def _row(i: dict) -> dict:
        return {"number": i["number"], "title": i["title"], "created_at": i["created_at"]}

    issues = [_row(i) for i in items if "pull_request" not in i]
    prs = [_row(i) for i in items if "pull_request" in i]
    return issues, prs


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: writes the watch-issue body and advances the watermark state file in place."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)

    top_level = subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True)
    repo_root = Path(top_level.stdout.strip())
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
        with Path(gh_output).open("a") as fh:
            fh.write(f"has_news={'true' if has_news else 'false'}\n")
    print(f"has_news={has_news} commits={len(commits)} issues={len(issues)} prs={len(prs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
