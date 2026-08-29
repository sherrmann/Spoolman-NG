# Spoolman NG vs. upstream Spoolman — feature & UI comparison

**Date:** 2026-08-28 · **Fork:** `40b0cf8` (v2026.8.3) · **Upstream:** `Donkie/Spoolman` `42721c7` (2026-08-27)

**Method:** a code-level diff of two working checkouts, not a comparison of documentation. Upstream
was cloned fresh and every claim below cites `path:line` in one tree or the other. Regenerate with:

```sh
git clone https://github.com/Donkie/Spoolman /tmp/upstream   # then diff against this checkout
```

This document complements, and in places supersedes, the other upstream docs here:

- `docs/upstream-triage.md` — a 2026-07-06 sweep of upstream's *then-open issues*. Still valid as
  history; it is not a comparison of the two codebases.
- `docs/upstream/ledger.json` / `SOLVED.md` — the port ledger, keyed on issue and commit IDs rather
  than on features. Its watermark is upstream `009f9e3b` (2026-08-23); upstream HEAD is `42721c7`,
  so **22 upstream commits are currently untriaged**.
- `docs/upstream/client-v2-fork-additions.md` — the mechanics of the vendored subtree, and the
  running list of what this fork adds to and edits inside it. It points back here for the feature
  comparison; this file does not duplicate its Tier 1/Tier 2 tables.

---

## Status note — which client this fork is building

This repository ships **two** web clients against one backend, and their roles are now asymmetric:

| | `client/` (React + refine + antd) | `client_v2/` (Svelte / SvelteKit) |
|---|---|---|
| Role | **Frozen.** No further feature work. | **Active.** All new feature work lands here. |
| Shipped? | Yes, and it remains the **default** (`SPOOLMAN_LEGACY_CLIENT` defaults `TRUE`) | Yes, opt-in per browser |
| Origin | Forked from upstream, then heavily extended | Vendored from upstream as a git subtree, extended additively |

Upstream has the same two clients with the **opposite** default: its `SPOOLMAN_LEGACY_CLIENT`
defaults `FALSE`, so upstream serves Svelte and treats React as the fallback
(`spoolman/env.py:555` upstream vs. `spoolman/env.py:775` here).

The practical consequence for this document: the React client's large feature surface is no longer
an asset to catalogue but a **parity backlog** for `client_v2`, and React's own gaps against upstream
are won't-fix. Both are recorded below rather than dropped.

---

## Headline

| Area | Spoolman NG | Upstream Spoolman |
|---|---|---|
| Version scheme | CalVer `2026.8.3` | SemVer `0.26.1` |
| API routers mounted | 20 | 10 |
| Database tables | 20 | 8 |
| Alembic migrations | 40 | 16 |
| Backend modules (`spoolman/*.py`) | 41 | 19 |
| Registered settings keys | 32 | 13 |
| Svelte client routes | 13 | 6 |
| React client page groups | 13 (frozen) | 8 (legacy fallback) |
| **Default client** | **React** | **Svelte** |
| Runtime client switching | Per-browser cookie + in-UI control | None — env var + restart |
| Backend test files | 214 | 65 |
| Playwright spec files | 60 | 18 |
| CI jobs in `ci.yml` | 26 | 13 |

**Nothing upstream has is missing from this fork as a whole feature.** There are zero upstream-only
backend modules and zero upstream-only Svelte routes. What upstream is ahead on is a small number of
specific fixes and one filter surface, listed next.

---

## Where upstream is ahead

Each row below was verified by hand against both checkouts.

### Actionable

| # | Gap | Evidence | Severity |
|---|---|---|---|
| 1 | **SQLite backup leaks two connections per run.** A `Connection` context manager commits, it does not close. The leaked handle also makes backup *rotation* fail on Windows ("file in use"); POSIX `unlink` hides it. Upstream fixed this with `contextlib.closing` in `21c7b98`. | fork `spoolman/database/database.py:161`; upstream `spoolman/database/database.py:133-141`, which carries a four-line comment explaining the failure mode | **Real bug, genuinely missed** — it appears in neither `SOLVED.md` nor `CHANGELOG.md` |
| 2 | **No Kubernetes service-link guard in `entrypoint.sh`.** Kubernetes injects `SPOOLMAN_PORT=tcp://<clusterIP>:8000` for any Service named `spoolman` in the namespace. uvicorn cannot bind that, so the container fails to start. Upstream sanitises it back to `8000` with a warning. | upstream `entrypoint.sh:13-22`; fork `entrypoint.sh:5` consumes the value raw | **Notable** — this fork ships a Helm chart (`charts/spoolman-ng`), so it is *more* exposed to this than upstream is |
| 3 | **Svelte client translation drift in 3 of 32 locales.** Affected strings include the NFC tag-linking dialogs, some validation messages, and parts of add-spool and the library toolbar; they fall back to English. | key counts in `client_v2/locales/*/common.json`: `de` 587 vs 616, `pl` 568 vs 626, `zh` 471 vs 606. The other 29 locales, `en` included, are byte-identical to upstream | Cosmetic — a subtree pull closes it |
| 4 | **`client_v2` renders a date filter that silently does nothing.** | `.github/workflows/ci.yml:352-362` says so directly: *"client_v2 sends the filter, the backend silently ignores it, and the list doesn't narrow"* | See below |

On (4): omitting the `first_used` / `last_used` / `registered` range filters and
`filament.multi_color_direction` from `GET /spool` is a deliberate, documented scope decision
(`spoolman/database/spool.py`, grep `this fork's filter surface`), and the vendored Playwright test
that covers them is excluded in CI by name. **That decision stands.** What does not stand is the
dead control: the client that all future work targets shows users a date filter that returns an
unnarrowed list. Either implement the filters or hide the control in `client_v2`.

### Known and accepted (React is frozen)

Both are real, user-visible defects in the client that remains the default. They are recorded rather
than dropped so that `client_v2` does not reproduce them when it reimplements extra fields.

| Gap | Evidence |
|---|---|
| An extra field cannot be cleared back to unset. `StringifiedExtras` never emits an explicit `null`, so emptying a single-choice / integer / range / datetime field silently keeps the old value. Upstream fixed it in `ae3208a`. | fork `client/src/components/extraFields.tsx:215-233`; upstream `client/src/components/extraFields.tsx:197-215` |
| Extra-field choice values cannot be reordered. Upstream added drag and arrow-key reordering in `18f1144`. | fork `client/src/pages/settings/extraFieldsSettings.tsx:231` is a bare `<Select mode="tags" open={false}/>`; upstream has `useDrag`/`useDrop` at `extraFieldsSettings.tsx:76-123` |

### Partial

Upstream has `GET /external/filament/search`, a server-side word match over the external catalogue
(`spoolman/api/v1/externaldb.py:37-58` upstream). This fork instead put rich query-param filters on
the list endpoint itself — `manufacturer`, `name`, `material`, `color_hex`, `diameter`, `weight`,
`id` (`spoolman/api/v1/externaldb.py:71-98`). Overlapping, not identical.

### Deliberate divergences, not gaps

- **Sponsorship link.** Upstream replaced its Ko-fi button with GitHub Sponsors (`a039095`); this
  fork keeps Ko-fi, pointing at a different maintainer. Intentional.
- **`requirements.txt`.** Upstream commits one; this fork gitignores it (`.gitignore:29`) and
  generates it at release time (`.github/workflows/ci.yml:675`, `uv export --frozen --no-dev`),
  which is what the README's Moonraker `update_manager` recipe consumes. Not a gap.

---

## React → Svelte parity backlog

All new feature work lands in `client_v2`, so this is the list that matters going forward. Every
"absent" claim was confirmed by grep against `client_v2/src`.

### Blocking defect — fix before any parity item

**`client_v2` never sends credentials, so it cannot be used on an instance with authentication
enabled.**

`client_v2/src/lib/api/` contains **zero** `Authorization` or `Bearer` references — none of the six
fetch wrappers in `http.ts` sets an auth header. The file's own premise says why:
`client_v2/src/lib/api/auth.ts:3` opens with *"Spoolman has no login of its own and never answers
401."* That is true of upstream. It is **false of this fork** — `spoolman/auth.py:188` rejects with
401 and `WWW-Authenticate`, backing both `SPOOLMAN_API_TOKEN` and the user-account system.

The React client has the whole path: `client/src/utils/apiToken.ts`,
`client/src/utils/authReloadHandler.ts`, a token query parameter for the websocket handshake
(`client/src/components/liveProvider.ts:75`, since browsers cannot set headers on a WS upgrade), and
authenticated image fetches (`client/src/components/entityImage.tsx:6`).

What a user hits today: set `SPOOLMAN_API_TOKEN` or create an account, switch to the Svelte client,
and every request 401s. The 401 handler in `auth.ts` then reloads the page — rate-limited to once
per 30 s, so not a hot loop, but the tab reloads indefinitely and never shows data. **This fork's
headline security feature and its designated future client are currently mutually exclusive.**

This is also why backlog item 9 below is sized L: it is not "add a modal", it is retrofitting auth
into every request path, very likely including the two websockets (`lib/api/live.ts`,
`lib/api/scanRelay.ts` — not audited).

### Backlog

Size weights how much already exists server-side: the backend endpoints for most of these are
already built and proven by the React client, making the work UI-only.

| # | Feature | React location | Size |
|---|---|---|---|
| 9 | Native login / API-token entry, and `Authorization` plumbing | `client/src/components/apiTokenModal.tsx`, `client/src/utils/apiToken.ts` | **L** |
| 3 | Resizable and drag-reorder column manager | `client/src/components/columnManager.tsx`, `resizableHeaderCell.tsx` | **L** |
| 23 | Photo intake / Scan-to-Spool | `client/src/components/photoIntake.tsx` | **L** |
| 2 | Multi-row selection with bulk edit / archive / weigh-in | `client/src/pages/spools/bulkEdit.tsx`, `bulkWeightUpdate.tsx` | M |
| 10 | User and account management UI | `client/src/pages/settings/usersSettings.tsx` | M |
| 11 | Swatches settings tab | `client/src/pages/settings/swatchSettings.tsx` | M |
| 12 | Swatch 3MF download | `client/src/components/swatchDownloadModal.tsx` | M |
| 13 | Import/Export settings tab | `client/src/pages/settings/importExportSettings.tsx` | M |
| 14 | 3MF slice-import spool matcher | `client/src/pages/settings/threeMfImport.tsx` | M |
| 15 | Printers settings, and the spool `printer_id` field | `client/src/pages/settings/printerSettings.tsx` | M |
| 19 | Filament image upload and display | `client/src/components/filamentImageUpload.tsx`, `entityImage.tsx` | M |
| 1 | Gallery / grid view for spools and filaments | `client/src/pages/spools/list.tsx:389-683` | S |
| 4 | Table totals row | `client/src/pages/spools/list.tsx:696-721` | S |
| 5 | Filament catalog fields (`spool_type`, `finish`, `pattern`, `translucent`, `glow`) | `client/src/pages/filaments/catalogFields.tsx` | S |
| 6 | Filament aggregate `remaining_weight` column | `client/src/pages/filaments/list.tsx:89-115` | S |
| 7 | Pre-print checklist modal | `client/src/pages/printing/prePrintChecklistModal.tsx` | S |
| 8 | Weight-history chart on the spool page | `client/src/pages/spools/weightHistoryChart.tsx` | S |
| 16 | Custom links (sidebar and per-spool actions) | `client/src/pages/settings/customLinksSettings.tsx` | S |
| 17 | Extra fields for `location`/`printer`, the `link` type, `copy_from_filament` | `client/src/utils/queryFields.ts:6-38` | S |
| 18 | `unit_scaling` setting | `client/src/utils/settings.ts:7-13` | S |
| 20 | Update-available notification | `client/src/components/updateNotification.tsx` | S |
| 21 | Error boundary that recovers from corrupt view state | `client/src/components/errorBoundary.tsx` | S |
| 22 | Low-stock count badge in the nav | `client/src/components/layout.tsx:37-78` | S |

Several of these are blocked less by effort than by architecture: `client_v2`'s library is a
fixed-field row plus a master-detail inspector (`client_v2/src/lib/components/library/SpoolRow.svelte:27-51`),
not a configurable table. Items 1, 3 and 4 imply that redesign, not just a component.

Three absences are structural rather than cosmetic: `printer` does not exist in `client_v2`'s type
layer at all (`grep printer_id client_v2/src` → 0 hits), `client_v2` never fetches usage events
(`grep usage_event client_v2/src` → 0 hits), and its `EntityType` is hardcoded to three entities
(`client_v2/src/lib/api/fields.ts:7`) against React's five (`client/src/utils/queryFields.ts:18-24`).

### Present in both, weaker in Svelte

- **Extra fields** lack the `link` field type and `copy_from_filament` inheritance, even for the
  three entities they do support (`client_v2/src/lib/api/fields.ts:9-30` vs.
  `client/src/utils/queryFields.ts:6-38`).
- **Colour-similarity filter** exists only inside the command-palette search box
  (`client_v2/src/lib/api/search.ts:64-79`), not as a persistent list filter alongside
  material/location/archived as in React (`client/src/pages/spools/list.tsx:223-234,548`).
- **NFC bind** reads the tag UID but does not decode or preview the manufacturer payload — colour,
  material, weight, temperatures — the way `client/src/components/nfcBindModal.tsx:30-100` does.
  `client_v2/src/lib/utils/nfc.ts:11` states there is no NDEF parsing. The decoder already exists at
  `client_v2/src/lib/ng/tigertagCodec.ts:118` for the write flow; it is simply not wired into bind.
  A small fix for a visible gap.
- **Editing** is panel-based (select a row, edit in the inspector) rather than inline in the table.
  Single-record editing is at parity; editing many rows in succession is materially slower.
- **AI settings** lack the ready-to-paste MCP client-config snippet
  (`client/src/pages/settings/aiSettings.tsx:370-401`).

### Already ported — do not re-file

AI settings, natural-language search, NFC writing, free-text search, `spool_count` and `external_id`,
extra-field display, and **filament and location label printing** — the last unified into the
`/labels` designer through a `LabelKind` union (`client_v2/src/lib/labels/types.ts:23`) rather than
the separate `/filament/print` and `/location/print` pages React uses.

### Present only in Svelte

- **Dashboard grouping board** — spools as draggable cards grouped by any field
  (`client_v2/src/routes/dashboard/+page.svelte`). React has no `/dashboard` route at all.
- **WYSIWYG label designer** — per-element canvas editing with saved named designs
  (`client_v2/src/lib/components/labels/LabelDesigner.svelte`). React's printing is a fixed template
  with options.
- **Hardware reader pairing and relay** — pair a browser to a networked reader by tapping a tag on
  it (`client_v2/src/lib/components/settings/ScannerSettings.svelte`, `lib/api/scanRelay.ts`).
  `grep -rln relay client/src` → no hits.

**Not deep-audited:** Calibration and Locations appear at or near parity by file and line evidence,
but were not verified field by field.

---

## Backend & API

Routers mounted in `spoolman/api/v1/router.py`: **20 here, 10 upstream**. The ten shared ones are
`filament`, `spool`, `vendor`, `setting`, `field`, `other`, `externaldb`, `export`, `search`, `tag`.
`field.py`, `search.py` and `other.py` are byte-identical between the two trees.

Fork-only routers:

| Router (prefix) | Endpoints | Purpose |
|---|---|---|
| `ai.py` (`/ai`) | `GET /status`; `POST /probe`, `/config`, `/spool-intake/extract`, `/spool-intake/match`, `/chat`, `/chat/action`, `/nl-search`, `/transcribe`, `/ollama/pull`; `GET /ollama/models` | AI provider foundation, Scan-to-Spool extraction, chat agent, NL search, voice transcription, managed Ollama pulls. Off by default. |
| `auth.py` (`/auth`) | `GET /status`, `/me`, `/users`; `POST /login`, `/users`; `PUT /users/{id}`; `DELETE /users/{id}` | Opt-in accounts with admin/read-only roles, layered over bearer-token auth. |
| `calibration.py` (`/calibration`) | CRUD on `/session`, `/session/{id}`, `/session/{id}/step`, `/step/{id}` | Filament calibration wizard sessions and steps. |
| `import_.py` (`/import`) | `POST /{entity}` | CSV/JSON bulk import, the inverse of `/export`. |
| `location.py` (`/locations`) | CRUD on `""`, `/{id}` | Locations as a first-class entity with extra fields. |
| `nfc.py` (`/nfc`) | `GET /status`; `POST /read`, `/write`, `/encode`, `/lookup`, `/bind`, `/create-from-tag` | Server-side NFC across TigerTag, Qidi and OpenPrintTag. |
| `order.py` (`/order`) | `GET ""`, `/{id}`; `POST ""`, `/{id}/arrive`; `PATCH /{id}`; `DELETE /{id}` | Purchase orders with partial delivery. |
| `printer.py` (`/printer`) | CRUD on `""`, `/{id}` | Printers as an entity, for per-printer usage attribution. |
| `shop.py` (`/shop`) | CRUD on `""`, `/{id}` | Shops that orders are placed against. |
| `stats.py` (`/stats`) | `GET /usage` | Historical usage statistics. |

Endpoint-level differences inside shared routers:

| Endpoint | Fork | Upstream |
|---|---|---|
| `GET /spool/{id}/events` (usage-event log) | yes (`spool.py:1044`) | no |
| `GET/PUT/DELETE /filament/{id}/image` | yes | no |
| `GET /export/filament/{id}/slicer` | yes | no |
| `GET /spool` — `search`, `archived`, `color_hex` + `color_similarity_threshold` | yes | no |
| `GET /spool` — `first_used`, `last_used`, `registered`, `filament.multi_color_direction` | **no** (deliberate) | yes |
| `GET /external/filament/search` | no | yes |
| `GET /external/filament` rich filters, `GET /external/profile/{id}` | yes | no |
| `POST /v1/update` (admin-gated self-update) | yes (`router.py:139-176`) | no |
| `GET /v1/info` extra fields | `update_check_enabled`, `latest_version`, `update_available`, `release_url`, `install_type`, `update_action_available`, `clients_available`, `client_active`, `client_switch_enabled` | base fields only |

There are **22 fork-only backend modules** and **zero upstream-only** ones: `ai.py`, `aichat.py`,
`assetlinks.py`, `auth.py`, `import_data.py`, `mcp_server.py`, `nfc_service.py`, `nlsearch.py`,
`ollama.py`, `openprinttag_codec.py`, `openprinttag_lookup.py`, `qidi_codec.py`, `qidi_lookup.py`,
`slicer_profiles.py`, `spoolintake.py`, `tigertag_codec.py`, `tigertag_lookup.py`, `tigertagdb.py`,
`updateaction.py`, `updatecheck.py`, `users.py`, `voice.py`.

`scanrelay.py`, `tags.py`, `colors.py`, `exceptions.py` and `filecache.py` are byte-identical to
upstream. `security.py` matches upstream function for function apart from a startup-logging change.
`ws.py` diverges by one fix this fork made: a dying subscriber no longer starves a whole event pool
(`ws.py:43-95` vs. upstream `ws.py:43-70`).

---

## Data model

**20 tables here, 8 upstream.** The eight shared: `vendor`, `filament`, `spool`, `setting`,
`vendor_field`, `filament_field`, `spool_field`, `tag`. The twelve fork-only: `image`, `shop`,
`purchase_order`, `order_line`, `spool_usage_event`, `calibration_session`,
`calibration_step_result`, `user_account`, `location`, `location_field`, `printer`, `printer_field`.

Column additions on shared tables (all fork-side; upstream adds none the fork lacks):

- **Filament** — `settings_extruder_temp_min`/`max`, `settings_bed_temp_min`/`max` (temperature
  *ranges* rather than single values), `spool_type`, `finish`, `pattern`, `translucent`, `glow`
  (SpoolmanDB catalogue descriptors), `color_hue` (precomputed for sorting), `low_stock_threshold`,
  `reserve_count`, `label_printed_at`, `image_id`.
- **Spool** — `diameter` (per-spool override), `printer_id`, `label_printed_at`.
- **Vendor**, **Setting**, **Tag** — same columns. `Tag` was ported from upstream
  (`fe4970567bb3`) and its docstring says so.

**Migrations:** 40 here, 16 upstream. **Settings keys:** 32 here, 13 upstream — every upstream key
exists here, plus 19 more (the `ai_*` family, `custom_links`, `spool_action_links`,
`extra_fields_location`, `extra_fields_printer`, `low_stock_fallback_g`, `print_presets_filament`,
`swatch_style`, `unit_scaling`).

**Extra-field system:** this fork adds `location` and `printer` as entity types, a `link` field type
with `link_template`, and `copy_from_filament` inheritance for spool fields. Upstream has
vendor/filament/spool and no `link` type.

---

## Svelte client vs. upstream

**The vendored subtree is at parity with upstream HEAD.** A full recursive diff of `client_v2/`
finds no upstream-only content: every shared file that differs does so only through this fork's own
additive edits, and `tests_frontend_v2/` and `client_v2/e2e/` are byte-identical to upstream. The
one exception is the locale drift noted above.

**13 routes here, 6 upstream.** Shared: `/`, `/dashboard`, `/labels`, `/settings`, and the
`filament/show/[id]` and `spool/show/[id]` redirects. Fork-only: `/home`, `/lowstock`, `/orders`,
`/locations`, `/calibration`, `/help`, `/location/show/[id]`.

Fork edits to shared pages:

| Page | Edit |
|---|---|
| `+layout.svelte` | Mounts `<AiChatLauncher />` (`:7,102`) |
| `/labels` | A third label type, Location, with the `L-<id>` QR scheme (`:143-159`) |
| `/settings` | An `AiSettings` panel, admin-only, plus the UI-client switcher (`:38-58,133-149`) |
| `/dashboard` | A remaining-weight gauge along the bottom edge of every spool chip (`:790-807,1089-1101`) |

Everything else the fork adds lives under `client_v2/src/lib/ng/` — 60+ files covering the AI, NFC,
calibration and orders APIs, NL search, voice, and their components, with ~25 co-located unit tests.
`client_v2/package.json` dependencies are **identical** to upstream's: none of this needed a new
library.

**i18n.** The fork keeps a second Paraglide catalogue in `client_v2/locales-ng/` with its own
`project-ng.inlang` and a second plugin instance in `vite.config.ts:12-22`, generated from the React
catalogue by `scripts/build_ng_messages.mjs`. This exists so that Weblate's constant rewriting of
`client_v2/locales/` — 9 of upstream's last 80 `client_v2` commits are pure translation merges —
cannot conflict with `git subtree pull`. Both runtimes share the `PARAGLIDE_LOCALE` key, so one
language selector drives both.

**Testing.** `tests_frontend_ng/` is fork-only: 13 specs, ~77 tests, covering the fork's own Svelte
pages plus the client switcher. Upstream has no equivalent.

---

## Which client you get

| | Fork | Upstream |
|---|---|---|
| `SPOOLMAN_LEGACY_CLIENT` default | `TRUE` → React (`spoolman/env.py:775`) | `FALSE` → Svelte (`spoolman/env.py:555`) |
| Switch at runtime | **Yes**, per browser, no restart | No — env var and a server restart, for everyone at once |
| Both bundles in the image | Yes, and the Dockerfile **builds** both (`Dockerfile:1-30`) | Yes, but `COPY`d in pre-built |

The fork's switcher (#405): `resolve_client_serving()` and `ClientSelector` in `spoolman/client.py`
mount both SPAs behind an ASGI wrapper that picks one per request from a `spoolman_ui` cookie.
`SPOOLMAN_UI_SWITCHER` (default `TRUE`) lets an operator disable it; switching is offered only when
both bundles actually exist on disk, so a source build of one client hides the control. `GET /info`
reports `clients_available`, `client_active` and `client_switch_enabled`
(`spoolman/api/v1/router.py:96-98`). Every URL is unchanged either way, so deep links, bookmarks and
printed QR labels keep working. Upstream has no equivalent.

---

## React client (frozen legacy)

Recorded for context on the parity backlog, not as live surface.

13 page groups against upstream's 8; fork-only routes are `/filament/print`, `/location/print`,
`/location/show/:id`, `/lowstock` and `/orders`. Shared pages are substantially denser here — the
spool list is 1002 lines against upstream's 476, the home page 623 against 126.

The spool list carries free-text and NL search, a colour-similarity filter, bulk weigh-in, a gallery
view, a drag-reorder column manager, a bulk-action bar, resizable columns, inline cell editing and a
totals row; upstream's toolbar is a strict subset of ours. The home page is a KPI dashboard with Low
Stock, Swatches, Materials, Vendors and Usage tabs where upstream's is a three-card stat page.
Settings adds Users, AI, Swatches, Import/Export, Printers and Custom Links tabs, and extends Extra
Fields from three sub-tabs to five.

`client/src/components/` is a strict superset of upstream's, with ~18 fork-only components. The nav
drops upstream's footer, moves version and sponsorship into the header, and adds a low-stock badge
and user-configurable links. Theming is the same engine plus explicit dark backgrounds and a
`components/layout.css` with mobile breakpoints upstream has none of.

**i18n:** 31 locale directories here against upstream's 32 — this fork adds `en-GB` as the default
and lacks `lv` and `sk` — but **1,138 keys** in the default catalogue against upstream's **294**,
because most of the strings cover fork-only features.

**Testing:** 77 unit and benchmark files under `client/src` plus a 43-file `client/e2e/` Playwright
suite and Stryker mutation testing. Upstream's `client/` has **zero** unit tests; its Playwright
lives in a separate `tests_frontend/` package.

---

## Deployment & operations

| Area | Fork | Upstream |
|---|---|---|
| Dockerfile | Builds both clients in a `client-builder` stage, so `docker build .` works from a clean checkout; `python:3.14-slim-trixie`; adds the `nfc` extra and USB libraries; `HEALTHCHECK`; `HOME` pinned for arbitrary-UID/OpenShift runs | Expects clients pre-built and `COPY`s them; `python:3.14-slim-bookworm`; no healthcheck; no arbitrary-UID pin |
| `entrypoint.sh` | Arbitrary-UID support, data-dir ownership healing, NFC device permissions | Kubernetes service-link `SPOOLMAN_PORT` sanitiser (**which this fork lacks — gap 2 above**) |
| Databases | SQLite, PostgreSQL, MySQL/MariaDB, CockroachDB | Same four |
| Architectures | amd64, arm64, armv7 | amd64, arm64, armv7 |
| Prometheus | Same gauges plus a `BUILD_INFO` metric (`prometheus/metrics.py:33`) | Same gauges |
| External sync | SpoolmanDB **and** TigerTag DB, plus on-demand 3dfilamentprofiles.com lookups | SpoolmanDB only |
| Extras | Helm chart, Expo mobile companion app, `integrations/` (KIAUH, Unraid, Zeabur, BigBear), an interactive install guide site | — |

---

## Quality & testing

| | Fork | Upstream |
|---|---|---|
| Backend test files | 214 | 65 |
| Playwright spec files | 60 | 18 |
| Mutation testing | Stryker (client) + mutmut (NFC codecs) | none |
| CI jobs in `ci.yml` | 26 | 13 |

Each side automates something the other does not. This fork has `ledger.yml` (regenerates
`SOLVED.md`) and `upstream-watch.yml` (polls upstream for new commits and issues), plus CodeQL,
hadolint, a deployment test, mobile APK builds and a non-root container test. Upstream has
`guard-translations.yml`, `weblate-automerge.yml` and `issue-manager.yml` — translation and issue-bot
automation this fork has no equivalent for, which is consistent with upstream running a hosted
Weblate project and this fork not.

---

## Maintenance

- The upstream watch ledger (`docs/upstream/watch-state.json`) is at `009f9e3b` (2026-08-23) against
  upstream HEAD `42721c7`: **22 commits untriaged**. Most are Weblate merges; the backend-relevant
  ones are covered above.
- This document supersedes the stale parts of `docs/upstream/client-v2-fork-additions.md`.
- The upstream checkout used to produce this comparison is ephemeral. The SHA is recorded at the top
  so a future pass can diff from the same point.
