# Org migration Phase 0 — trial findings

**Status:** IN PROGRESS (Stages A–C running; pilot transfer not started) · **Trial org:** `spoolman-ng-trial` · **Started:** 2026-07-16 · **Design:** `docs/superpowers/specs/2026-07-15-org-process-layer-design.md` §D · **Raw evidence:** `~/spoolman/phase0-evidence/` (local, not committed)

This doc is the input to the Phase 0→1 review gate. Nothing in Phases 1–2 (real org, SpoolmanDB, main repo) starts until this is reviewed.

## 1. Org creation

- Web-UI only (no API/CLI endpoint on github.com). Created 2026-07-16 19:10 UTC via the "New organization" flow, Free plan, owned by personal account, no members.
- Payment prompt during signup: _pending Sam's confirmation (expected: none)_.
- API confirms: `plan.name=free`, creator role `admin`.

## 2. Actions on the Free org (public repo)

- First push-triggered run of `spoolman-ng-trial/scratch-ci` workflow `trial` (run 29527313047) **succeeded** with **no payment method on the org** — jobs: probe (echo), multi-arch (amd64+arm64) docker build+push to ghcr, Pages deploy.
- Scheduled (`*/30` cron) run: **succeeded** (run 29532169210, event `schedule` — probe+ghcr green, pages skipped by design). Observed lag on the brand-new repo: workflow pushed 19:15 UTC, first cron pickup ~20:3x UTC — the 19:30 and 20:00 ticks were skipped entirely. **Phase 1/2 note:** expect freshly-migrated repos' cron workflows (Monday watch/ledger/sync, weekly mutation) to skip their first tick(s); don't diagnose failure until a couple of slots have passed.
- **Student-subscription relevance:** the org is a separate billing entity on its own Free plan; personal student/Pro benefits are not involved. Actions on public repos ran free regardless. (Billing evidence in §3.)

## 3. Billing — VERIFIED $0

- UI (Sam, 2026-07-16): Usage page shows **$0.03 "included usage"** — that is the gross value of consumed minutes, fully covered.
- API `GET /organizations/spoolman-ng-trial/settings/billing/usage` (enhanced billing platform): `actions / "Actions Linux" / 5.0 minutes @ $0.006 → grossAmount $0.03, discountAmount $0.03, netAmount $0.00`. **Public-repo minutes are zero-rated via a 100% discount**, not drawn from the 2,000-min private allowance — unlimited public CI stays $0 by policy.
- **Token scope (empirical):** the billing usage endpoint worked with the existing OAuth token (`repo` + `read:org`) for the org owner — `admin:org` NOT required (undocumented; docs only say "organization administrator role").
- No payment method on file; nothing billable. **Conclusion for the gating question: the org runs the fork's Actions free on its own Free plan; personal student/Pro benefits are not involved.**

## 4. OAuth app restrictions — RESOLVED

- Org Settings → Third-party Access (checked 2026-07-16): **"Policy: Access restricted"** — the documented new-org default holds. No pending requests, no grants ever made.
- Yet the `gh` CLI (OAuth token `gho_`, scopes `gist, read:org, repo, workflow`) created the org repo, pushed (incl. a workflow file), and called the Pages API **immediately, with no grant step**.
- Explanation: the policy is a *third-party* application policy; the **GitHub CLI is a first-party GitHub-owned OAuth app** and is not subject to it.
- **Phase 1 runbook consequence:** no grant step needed for `gh`/git day-to-day work. But any genuinely third-party OAuth app that should touch the repos after migration (integrations authorized on the personal account) must be individually approved for the org — audit the [authorized OAuth apps list](https://github.com/settings/applications) before Phase 1.

## 5. Token matrix

| Token | Result |
|---|---|
| `gh` OAuth (`gho_`, `repo`+`workflow` scopes) | Org repo create, git push, Pages-enable API: **worked** (§4). Org-admin reads (`orgs/*/actions/permissions`): 403, needs `admin:org` scope. Packages API reads: 403, needs `read:packages`. |
| Classic PAT (`secrets.PAT`, main repo) | _pending — tested by the pilot release (Stage D)_ |
| Fine-grained PATs | Not tested; docs: enabled by default but each token needs org-owner approval by default. |

## 6. Org Actions defaults (repo-level reads; org-level needs `admin:org`)

- `actions/permissions` (repo): `enabled: true`, `allowed_actions: all` (third-party `docker/*` actions ran; `sha_pinning_required: false`).
- `actions/permissions/workflow` (repo): `default_workflow_permissions: read`, `can_approve_pull_request_reviews: false` — **as docs predicted**: workflows in the org need explicit `permissions:` blocks for any write (scratch workflow declares `contents: read, packages: write, pages: write, id-token: write`).
- Action item confirmed for Phase 1: audit all three repos' workflows for reliance on default GITHUB_TOKEN write permissions before transfer.

## 7. Transfer preservation matrix

_Pending — Stage D pilot (before/after snapshots of stars, watchers, issues, branch protection, allow_auto_merge, delete_branch_on_merge, Actions state, webhooks)._

## 8. Redirect matrix

_Pending — Stage D: web 301, git clone/fetch/push via old URL, REST GET via old path, and the key one: `gh pr create --repo sherrmann/spoolman-ng-addons` from the unchanged `sync-ha-addon` job while the repo lives in the org._

## 9. Namespace retirement / traffic

- Threshold: >100 clones (or >100 Actions uses) in the week before transfer permanently retires the old namespace → blocks transfer-back at the original name.
- Measured 2026-07-16: addons repo trailing 7 days ≈ **96 clones** (spikes on release days: 46 on Jul 10, 22 on Jul 15 — HA instances clone on update). **Right at the line** → pilot timing decision at Checkpoint 1.
- Already-known implication for Phase 2: the main repo will very likely trip retirement → Phase 2 is effectively one-way.

## 10. Pages / ghcr in the org

- Pages on Free org public repo: enabled via `POST /repos/.../pages` `build_type=workflow`, deployed by `actions/deploy-pages`, serves **HTTP 200** at `https://spoolman-ng-trial.github.io/scratch-ci/`.
- ghcr package `ghcr.io/spoolman-ng-trial/scratch-ci`: created **private by default** (anonymous manifest fetch 403). Visibility change is web-UI-only, irreversible (public→private not allowed). After the flip (2026-07-16): anonymous registry-API manifest fetch **200**, anonymous `docker pull` + `docker run` **work**, manifest lists **amd64 + arm64** — org-namespace ghcr publish fully verified. The package carries `org.opencontainers.image.source = https://github.com/spoolman-ng-trial/scratch-ci`, connecting it to the source repo.
- **New-org packages policy blocks public packages by default**: the package's "Change visibility" control showed "setting is disabled by organisation administrators" even for the org owner, until the org-level toggle (org Settings → Packages → Package creation → Public) was enabled. **Phase 1/2 runbook item:** enable public package creation in the real org BEFORE the first release publishes ghcr images, or the org-side `spoolman-ng` package will be created private and HA installs / docker pulls will 403.
- Reminder (docs): packages are owner-scoped — `ghcr.io/sherrmann/spoolman-ng` will NOT move with any repo transfer; Pages URLs do NOT redirect.

## 11. Rollback round-trip

_Pending — Stage E._

## 12. Anomalies / residual risks

- ~~§4 OAuth surprise~~ — resolved: first-party GitHub apps bypass the third-party policy (§4).
- Nothing else so far.
