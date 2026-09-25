# Retiring the classic (React) client

Status: planned. Nothing built yet.

The React client in `client/` is frozen: no feature work goes into it, and all new work goes into
the Svelte client in `client_v2/`. It is still what a visitor gets by default
(`SPOOLMAN_LEGACY_CLIENT` defaults to `TRUE`, `spoolman/env.py:775`). This plan takes the project
from there to a repository with no `client/` directory, in steps that can each be merged and
released on their own.

It builds on #411, which listed 22 gaps; 20 are closed. A second audit (2026-09-25) covered the
areas #411 did not check field by field and found 18 more. Both sets are in section 2.

## 1. Order of work

| Phase | What | PRs | Gate before the next phase |
|---|---|---|---|
| A | Close the parity gaps in `client_v2` | A1–A9 | All merged |
| B | Make the Svelte client the default; the switcher stays | B1 | Released, then a trial period (section 5) |
| C | Remove every dependency on `client/` from outside it | C1–C4 | All merged |
| D | Delete `client/` and the code that only served it | D1 | Owner approves the PR |
| E | Close-out | E1 | — |

Phase C does not depend on B and can run during B's trial period.

## 2. Phase A: parity gaps

Each PR follows the fork rule from
[`client-v2-fork-additions.md`](../upstream/client-v2-fork-additions.md): new code goes under
`client_v2/src/lib/ng/`, an upstream file is changed by a line or two at most, and every such
change is recorded as Tier 2. Sizes: S = a day or less, M = a few days, L = a week.

**A1 — Links into the classic client keep working (S–M).** Printed labels, bookmarks, Moonraker
front-ends and custom links use React URLs. Only `/spool/show/:id`, `/filament/show/:id` and
`/location/show/:id` have a Svelte route today; everything else ends on the 404 page.

- `/spool`, `/filament`, `/vendor` → the library
- `/vendor/show/:id` → `/?sel=vendor:<id>`
- `/{spool,filament,vendor}/{create,edit/:id,clone/:id}` → the library with the matching modal or
  inspector open; `/spool/create?filament_id=` preselects the filament
- `/spool/print`, `/filament/print`, `/location/print` → `/labels` with the items preselected
- `/settings/<tab>[/<sub>]` → `/settings`, scrolled to that section
- `/filament/show/:id?tab=calibration` → `/calibration?filament=<id>`; today the redirect drops the
  query

Needs a URL parameter that opens the add-spool modal. Tests: one browser test per redirect in
`tests_frontend_ng`.

**A2 — Filaments and vendors on their own (M).** Today a filament can only be created while
adding a spool (the count must be at least 1) or while changing a spool's filament. A vendor is
only created as a side effect of typing its name. New Order needs a filament that already exists,
so this gap blocks a real workflow.

- "New filament" (with the SpoolmanDB import) and "New manufacturer" (name, comment, empty-spool
  weight, `external_id`) in the library's add menu
- Home's quick-create buttons for spool, filament and manufacturer
- `external_id` editable on the vendor inspector (read-only today)

**A3 — Spool actions (S).** Clone a spool. "Reset usage" (sets `used_weight` to 0 and clears first
and last used). The usage-history table (time, type, change, comment) under the weight chart; the
data is already fetched by `listSpoolEvents`.

**A4 — Filament fields and small actions (S).**

- Editable `reserve_count`, extruder and bed temperature ranges, and a filament's
  `low_stock_threshold` from its inspector (today only from rows on `/lowstock` and `/home`)
- Slicer-profile download for PrusaSlicer, OrcaSlicer and Cura (API: `spoolman/api/v1/export.py:76`)
- "Print label" on the filament inspector and the location page
- The on-order banner with "Mark arrived" when adding a spool of a filament that is on order
- The shop name on the "ordered" pill on Low stock and Home (the component supports it; the callers
  do not pass it)
- A way to close an abandoned calibration session without finishing the wizard

**A5 — NFC through the server reader (M).** The Svelte client reads only a tag's UID in the
browser and never calls `/nfc/read`, `/nfc/bind` or `/nfc/create-from-tag`. Port reading through a
USB reader attached to the server, binding a tag to a spool, decoding TigerTag and Qidi data from
tags read in the browser, and creating a spool from an unknown tag. `lib/ng/tigertagCodec.ts`
already exists. Device testing follows `docs/device-testing-list.md`; what cannot be tested
without hardware is listed in the PR.

**A6 — 3MF slice-import matcher (M).** Step 2 of [`import-export.md`](import-export.md), as
designed there. Closes #414.

**A7 — Photo intake / Scan-to-Spool (L).** As described in #418. In the same PR, drop
`absentHere` for this feature and replace the "Available in the classic interface" text
(`aiFeatures.ts`, `AiSettings.svelte`) for MCP, which has no client UI in either client. Closes
#418.

**A8 — Languages and the fork's string catalogue (M).** This is a parity gap and a deletion
blocker at once.

- `scripts/build_ng_messages.mjs` generates `client_v2/locales-ng` *from*
  `client/public/locales`, and CI fails if the output is stale. The fork's Svelte strings
  therefore have no source of their own. Make `client_v2/locales-ng/*.json` the source, remove the
  generator and the CI staleness check, and move the translation workflow in `CONTRIBUTING.md`, the
  PR template, and the `REVIEW.md` for translations to `client_v2`.
- The classic client offers UK English (the default) and US English separately; the Svelte client
  has one "English" using UK date and number formats with upstream's wording. Add `en-GB` as the
  default and keep `en` as US English, matching the classic client and the README.
- `et`, `hi-Latn`, `ko` and `sl` have upstream locale folders but are not in
  `project.inlang/settings.json`, and have no `locales-ng` file. Add them. The 26 existing
  `locales-ng` files cover 90–93% of the English keys; fill the missing keys.

**A9 — Accepted losses (no PR, recorded in the B1 changelog entry).** Unless the owner says
otherwise, these are not ported:

- The Cmd/Ctrl+K command palette (Refine's `RefineKbar`). Search and the bottom navigation cover
  navigation.
- The Ko-fi link in the header. The Help page's About block already has a sponsor link.
- Offline precaching of the app's files. The Svelte client is installable but needs the server to
  load, which it needs for data anyway.

After A1–A8 merge, #411 is updated with the new items ticked and closed.

## 3. Phase B: the default flip

**B1 (S).** One PR:

- `SPOOLMAN_LEGACY_CLIENT` defaults to `FALSE`; the docstrings in `env.py`, the comments in
  `main.py`, `client.py` and the `Dockerfile` stop calling React the default; `/info`'s
  `client_active` default becomes `"svelte"` (`spoolman/api/v1/models.py:1234`)
- A test that the default with no variable set is the Svelte client
- `docs/installation.md`, `docs/device-testing-list.md`, `docs/upstream/comparison.md`,
  `docs/design/library-table-parity.md`, `.env.example` (which does not document the variable yet)
  and the `running-spoolman` skill updated
- The switcher stays, so each browser can still go back. Its labels change from "new/classic" to
  plain names
- CI keeps setting `SPOOLMAN_LEGACY_CLIENT=FALSE` explicitly where it does today
- The README screenshot is replaced with the Svelte client
- A changelog entry that says what changed, how to go back (the switcher, or
  `SPOOLMAN_LEGACY_CLIENT=TRUE`), and what will not be ported (A9)

A browser that never picked a client moves to the Svelte one on upgrade. One that picked with the
switcher keeps its choice.

## 4. Phase C: removing dependencies on `client/`

None of these delete anything a user can see. They make D1 a deletion only.

**C1 — Mobile app (S).** `mobile/scripts/sync-shared.mjs` copies `client/src/utils/scan.ts` during
`npm ci`, so the mobile build fails once `client/` is gone. Point it at the Svelte client's scan
parser (`client_v2/src/lib/ng/scanCodes.ts`) after checking the two parse the same codes, and keep
the drift test. Update the comments that name the React client.

**C2 — Release tooling (S).** `spoolman/bump.py` bumps `client/package.json` and its lock file and
never touches `client_v2/package.json`. Move it to `client_v2`. `lefthook.yml`'s `ci` block runs
lint, format and type checks for `client/` only; add the same for `client_v2`, so CI still checks a
frontend once `client/` is gone.

**C3 — Tests that go through the React client but test the server (M).**
`tests/test_ingress.py`, `tests/test_assetlinks.py` and `tests/integration/test_client_static.py`
exercise Home Assistant ingress, asset links and static serving through the React serving mode.
Those server features stay, so the tests are ported to the Svelte serving mode, not deleted.
`tests_scenarios/assertions/e2e.py` runs `client/e2e/external.spec.ts`; port that spec to
`tests_frontend_ng`.

**C4 — Mutation testing (M).** The weekly Stryker run (`mutation.yml`, a 90% gate) covers only the
React client. Set it up for `client_v2/src/lib/ng/`, measure the score first, and set the gate at
that score, not at 90%, so the job does not start out red.

Smaller items go into whichever C PR touches the area: the icon URLs in
`integrations/unraid/spoolman-ng.xml` and `integrations/zeabur/*.yaml` move to
`client_v2/static/pwa-512x512.png`, and the comment in `spoolman/settings.py:73` points at the
Svelte swatch code.

## 5. Trial period between B and D

D1 is not merged until:

- a release containing B1 has been out for at least two weeks, and has been followed by at least
  one more release
- no open issue reports something the classic client did that the Svelte client cannot do

A report in that time that points to something missing from section 2 becomes a Phase A PR, and
restarts the two weeks only if it blocks a real workflow.

## 6. Phase D: deletion

**D1 (L, mostly deletion).** One PR, opened after section 5 is met and merged only after the owner
approves it:

- Delete `client/`.
- Build: remove the React stage from the `Dockerfile` and the `client/` entries from
  `.dockerignore` (and add `client_v2/node_modules` and `client_v2/build`).
- CI:
  - Remove the `client-tests` and `e2e` jobs and take them out of `publish-images.needs`.
  - Remove the React steps from `style`, `build-client` and `tests-frontend-ng`.
  - Remove `client-mutation` from `mutation.yml`, and `client-tests` from
    `.forgejo/workflows/tests.yml`.
  - Remove `/client` from `dependabot.yml`.
- Server:
  - `client.py` and `main.py` mount only the Svelte client. Remove the selector, the
    `spoolman_ui` cookie and the React-only index and manifest rewriting.
  - `SPOOLMAN_LEGACY_CLIENT=TRUE` and `SPOOLMAN_UI_SWITCHER` still parse, but log a warning that
    they no longer do anything, so no existing install fails to start.
  - `/info` keeps `clients_available`, `client_active` and `client_switch_enabled` with fixed
    values (`["svelte"]`, `"svelte"`, `false`), so API clients that read them keep working.
- Svelte client: remove the Settings switcher row, `lib/uiClient.ts` and its test, and the
  `ui_version_*` strings.
- Keep `client_v2/static/sw.js` and `tests_frontend_v2/tests/legacy-sw.spec.ts`. They remove the
  React client's service worker from browsers that still have it, and are needed for as long as
  such browsers exist.
- Tests: delete `tests/integration/test_client_selector.py`, the React cases in
  `tests/test_client_serving.py` and `tests/test_manifest_tweak.py`, `ui-switch.spec.ts`,
  `build_legacy_client()` in `tests_frontend_v2/run.py`, and the `client/dist` check in
  `tests_deployment/test_release_zip.py`. Remove the `client/e2e` ruff ignore from
  `pyproject.toml`.
- Docs: rewrite the React sections of `CONTRIBUTING.md` and `TESTING_STRATEGY.md`. Update the paths
  in `CLAUDE.md`, `README.md` (the Forgejo note), `docs/mobile-companion-app.md`,
  `docs/upstream/*.md`, `docs/design/*.md` and `MASTERPLAN.md`. Leave `docs/archive/` as it is.
- Changelog: a "Removed" entry.

The full list of references, with line numbers, was collected on 2026-09-25. It is re-collected
when D1 starts, because the files will have changed by then.

## 7. Phase E: close-out

**E1.** Close #411. In `docs/upstream/comparison.md`, record that the fork now matches upstream's
client arrangement: Svelte only, with no legacy client. Upstream still keeps its React client
behind `SPOOLMAN_LEGACY_CLIENT`.

## 8. How the work runs

- **One PR at a time on `claude/wonderful-dirac-uu4rap`.** That is the only branch the automated
  sessions may push to, so PRs are sequential. After a PR merges, the branch is restarted from
  `master` for the next one.
- **Each PR:**
  - An implementer agent does the routine parts. Design decisions, the server code, and anything
    touching auth, NFC or data writes stay with the main session.
  - The reviewer agent runs after each substantial step and on the full diff before the push, and
    every finding is fixed or answered.
  - Before pushing, these must pass:
    - `uv run ruff check`, `uv run ruff format --check` and the affected pytest files
    - in `client_v2`: `npm run lint`, `npm run check` and `npm test`
    - the affected Playwright specs in `tests_frontend_ng`
    - for UI changes, a screenshot at desktop and phone width through the `running-spoolman` skill
  - Every PR has a changelog entry under Unreleased.
- **After a PR is opened:** the session watches it, fixes CI failures and review findings, and
  checks in hourly until the PR is green and mergeable.
- **Between PRs:** when a PR is green and waiting only for a merge, the session starts the next
  independent step locally but does not push it until the previous PR has merged.
- **Tracking:** one issue, "Retire the classic client", with one checklist line per PR above,
  linked from #411.

## 9. Decisions for the owner

Each has the answer this plan assumes if nobody objects.

1. **Who merges.** Assumed: the owner merges each PR; the session gets it green and says so. If the
   session may merge PRs once CI is green and review threads are answered, A1–C4 can run without waiting, and
   only D1 waits for the owner.
2. **Who releases.** Assumed: the owner runs the release workflow. The trial period in section 5
   starts with the release that contains B1.
3. **Photo intake.** Assumed: port it (A7). The alternative is to drop it and remove the setting.
4. **Command palette, Ko-fi link, offline precaching.** Assumed: not ported (A9).
5. **UK English.** Assumed: `en-GB` becomes the Svelte client's default language, as in the classic
   client (A8).
6. **Mutation testing.** Assumed: set up for `client_v2`, with the gate at the measured score (C4).
7. **Trial period.** Assumed: two weeks and two releases (section 5).
