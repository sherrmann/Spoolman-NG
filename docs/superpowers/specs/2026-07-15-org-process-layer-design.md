# Spoolman-NG organisation & process layer — design

**Date:** 2026-07-15 · **Status:** draft for review · **Scope:** the three repos `Spoolman-NG` (this repo), `spoolman-ng-addons`, `SpoolmanDB` (sherrmann forks)

## Context

Spoolman-NG is a maintained hard fork of `Donkie/Spoolman`. A one-time upstream backlog sweep (2026-07-06, `docs/upstream-triage.md`) triaged all 265 open upstream issues into 98 fork issues covering 132 upstream issues plus 133 documented skips. Since then there is no ongoing process for: new upstream commits (currently 27 behind), new upstream issues, or answering "which upstream issues has the fork solved" from live data. Upstream became active again in July 2026 (v0.24.0), so drift is now recurring, not one-time.

Verified facts this design rests on:

- The fork's upstream references (issue bodies, triage doc) are written in backticks, so GitHub never linked them: **upstream's issue tracker contains zero cross-references to this fork** (checked Donkie/Spoolman#217's timeline).
- Unbackticked `owner/repo#N` or full-URL references in PR/issue bodies and commit messages create quiet "mentioned this" timeline events in the upstream issue. No notifications are sent to subscribers; this is standard OSS cross-linking.
- `spoolman-ng-addons` has zero CI and receives direct-to-master pushes from a classic-PAT-driven sync job in this repo's release pipeline.
- `SpoolmanDB` (fork) has no upstream auto-sync (MASTERPLAN §6 P0); its current 46-ahead/0-behind state came from a one-time manual merge.

## Decisions already made (with maintainer)

1. **Watch cadence: weekly** (Mondays, alongside the existing mutation-testing schedule).
2. **Upstream visibility: organic only.** Going forward, upstream references in fork PRs/issues/commits are written unbackticked so GitHub cross-links them. No retroactive editing of the 98 existing issue bodies (would fire ~132 timeline events upstream at once). No mass commenting on upstream issues. Whether to hand-write comments on a few high-traffic upstream issues is deferred to the fork-announcement milestone.
3. **Organisation: trial first.** No blind transfer. Phase 0 (below) empirically verifies cost/behavior before any real repo moves.
4. **Secrets stay (2026-07-15).** The existing classic PAT keeps powering the release/bump pipeline. Fine-grained PAT / GitHub App migration is deferred — natural revisit point is the org migration, which forces a secrets review anyway.

---

## A. Upstream-solved ledger

**Purpose:** a continuously-correct answer to "which upstream issues did we solve, where, and in which release".

**Component:** `scripts/upstream_ledger.py` (stdlib + `gh` CLI subprocess or GitHub REST via token; no new runtime deps).

**Inputs:**
- `docs/upstream-triage.md` — authoritative fork-issue ↔ upstream-issue mapping from the sweep (parse the markdown tables; they are machine-regular).
- Fork issue bodies — `**Upstream:** …#NNN` markers (covers issues created after the sweep, by convention below).
- GitHub state via API: fork issue open/closed, closing PR, merge commit.
- `git tag --contains <merge-commit>` — first release containing the fix.
- Port-PR trailers (see B): `Upstream-commit: <sha> ported|skipped — <reason>`.

**Outputs (both committed):**
- `docs/upstream/SOLVED.md` — three tables: **Solved** (upstream # → fork issue → PR → released in), **In progress** (fork issue still open), **Skipped** (from the sweep's skip list, with reasons).
- `docs/upstream/ledger.json` — same data machine-readable, for release notes and any future website/badge use.

**Wiring:** a job in the release path regenerates both files and includes an "Upstream issues addressed in this release" section in the auto-generated release notes. A weekly regeneration also runs with the watch workflow (B) so the doc can't rot between releases.

**Convention (new, documented in CONTRIBUTING.md):** any fork issue/PR addressing an upstream issue includes a plain-text line `Upstream: https://github.com/Donkie/Spoolman/issues/NNN` — unbackticked, so the ledger parses it *and* GitHub cross-links it upstream.

**Error handling:** unparseable triage rows or API failures fail the job loudly (exit non-zero, workflow red) rather than emitting a partial ledger; the previous committed ledger remains valid.

## B. Weekly upstream watch

**Purpose:** turn the one-time sweep into a standing process for upstream commits, issues, and PRs.

**Component:** `.github/workflows/upstream-watch.yml`, `schedule: cron Monday` + `workflow_dispatch`.

**State:** `docs/upstream/watch-state.json` — `{ last_commit_sha, last_issue_seen_at, last_pr_seen_at }`. The workflow advances the watermark by committing the updated file (same-repo push, no PAT needed beyond `GITHUB_TOKEN` with `contents: write`).

**Behavior per run:**
1. Fetch `Donkie/Spoolman` master; list commits since `last_commit_sha` (oneline + touched top-level dirs as a porting hint).
2. List upstream issues and PRs created since the timestamps.
3. If everything is empty: exit silently (no issue created).
4. Otherwise create **one issue for that week**, labeled `upstream-watch`, with three checklist sections (commits: port/skip each; issues: fix/implement/skip, mirroring sweep verdicts; PRs: mine/ignore). Checklists are worked through manually; verdicts are recorded where the work happens:
   - Ported commits: the port PR carries `Upstream-commit: <sha> ported` trailer.
   - Skipped commits: checked off in the watch issue with a one-line reason; a tiny closing step (checkbox-complete → maintainer closes issue) is acceptable — no automation parses the issue in v1.
5. First run seeds `last_commit_sha` to the current merge-base, so run #1 generates the catch-up issue for the existing 27-commit backlog.

**Non-goals (v1):** no auto-porting, no auto-triage of upstream issues, no parsing of checkbox state back into the ledger. The ledger learns about ports only from PR trailers.

### B2. SpoolmanDB auto-sync (separate repo, same spirit)

`.github/workflows/upstream-sync.yml` in the SpoolmanDB fork, weekly: fetch `Donkie/SpoolmanDB` main; if new commits, open a merge PR (branch `upstream-sync/YYYY-Www`) with auto-merge enabled — the existing schema/build CI is the gate. On merge conflict: push the conflicted branch is impossible, so instead open an issue labeled `upstream-sync-conflict` listing the divergent files. Closes MASTERPLAN §6 P0.

## C. CI/CD hardening

1. **spoolman-ng-addons CI (from zero):** one workflow with two jobs on PR + push-to-master: (a) `frenck/action-addon-linter` against `spoolman_ng/` + yamllint; (b) amd64 docker build smoke of the add-on. Branch protection on master requiring both.
2. **Version-bump sync becomes a PR:** the release pipeline's direct push to spoolman-ng-addons changes to "create branch + PR with auto-merge". Same automation, now gated by the new lint and auditable. (Requires the addons repo to allow auto-merge.)
3. **Secrets: deferred** (decision 4). The classic PAT stays; C2's PR-based sync works with it unchanged. Revisit at org migration.
4. **Dependabot** in spoolman-ng-addons (`github-actions`, `docker` ecosystems), matching the other two repos.
5. **Release notes:** enable GitHub auto-generated notes (`.github/release.yml` categories from labels) + the ledger section from A.
6. **Explicitly out of scope now:** per-PR mutation testing (weekly stays), SHA-pinning all actions (separate chore), CodeQL on the addons repo (nothing to scan).

## D. Organisation migration — trial-gated

**Phase 0 — trial (no real repo moves):**
1. Create a free **throwaway trial org** (e.g. `spoolman-ng-trial`) — the real org name (`spoolman-ng` proposed) is decided at the Phase 0→1 review gate, because GitHub org names are hard to reclaim after deletion and the trial shouldn't burn the good name.
2. Create a public scratch repo in it with a workflow exercising: scheduled + push-triggered Actions runs, a ghcr.io package publish under the org namespace, and a Pages deploy.
3. Verify empirically: Actions run without a payment method and the org's billing page shows $0 / "Free" plan with public-repo usage not metered; ghcr package is pullable anonymously; Pages serves.
4. Pilot transfer: move **spoolman-ng-addons** (lowest stakes: no packages, no Pages, no external links yet) into the org. Verify: web + git redirects work, issues/stars intact, what happened to repo secrets and branch protection, and that the release pipeline's bump job — still using the existing classic PAT — works against the transferred repo (classic PATs cover org repos the user can access, unless the org restricts them; verifying this is a trial goal).
5. Document findings in the migration checklist; **stop here and review** before Phase 1.

**Phase 1 — SpoolmanDB transfer:** transfer repo; Pages URL changes to `<org>.github.io/SpoolmanDB`. Transition: keep a stub `SpoolmanDB` repo on the personal account whose scheduled workflow republishes the org build's `filaments.json` to the old Pages URL for **6 months** (sunset date recorded in the stub README). New releases point `EXTERNAL_DB_URL` default at the org URL.

**Phase 2 — main repo transfer:** transfer `Spoolman-NG`; update `ghcr.io` publish to **dual-publish** (`ghcr.io/sherrmann/spoolman-ng` + `ghcr.io/<org>/spoolman-ng`) for **3 months** (noted in the README with the sunset date), then sunset the personal path. Docker Hub (`cookiemonster95`) unaffected. Update README/Moonraker `update_manager` docs (git redirects make this non-urgent but it should be same-release). Re-create repo secrets if the transfer drops them (re-add the existing PAT secret; the Phase 0 pilot will have established the exact behavior).

**Rollback:** GitHub allows transferring back; redirects then point the other way. The trial phase exists precisely so Phases 1–2 only run with verified facts.

## Build order

Independent pieces, cheapest-first: **C1/C4 (addons CI + dependabot) → A (ledger) → B (watch) → B2 (SpoolmanDB sync) → C2 (PR-based sync) → D Phase 0 (org trial) → review gate → D Phases 1–2.**

## Testing

- Ledger: unit-test the triage-table parser against the real `docs/upstream-triage.md` (fixtures from it); dry-run mode (`--check`) that diffs instead of writing, used in CI.
- Watch: `workflow_dispatch` run against a fixed watermark in a branch; assert issue body renders and watermark commit lands.
- Addons CI: intentionally-broken `config.yaml` on a branch must fail the linter.
- Org trial: is itself the test (Phase 0 checklist).

## Out of scope

Fork announcement content/channels, upstream-comment outreach, FUNDING/Ko-fi decision, Weblate, monetization Track-1 auth work, per-tool/slot data model — all tracked elsewhere (MASTERPLAN / MONETIZATION_PLAN).
