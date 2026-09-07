# Library table parity in the Svelte client (#412)

**Status:** design proposal, no code. **Date:** 2026-09-07. **Fork:** `client_v2` subtree at
upstream `42721c7` (2026-08-27); upstream HEAD `81636f25` (2026-09-04).

Issue #412 groups four things the frozen React client does and the Svelte library cannot:
a gallery view, multi-row selection with bulk edit / archive / weigh-in, a column manager, and a
totals row. The issue is right that this is an architecture decision first: `client_v2`'s
library is a fixed-field row plus a master-detail inspector, and every one of the four needs
something the row does not have. This document settles how to add them while honouring the
vendored-subtree rule in [`../upstream/client-v2-fork-additions.md`](../upstream/client-v2-fork-additions.md):
**add files, do not edit files.**

Every claim below cites a path and line in this checkout or in `upstream/master` as fetched on
2026-09-07. Line numbers drift; the file names do not.

---

## 1. What exists today

### 1.1 The Svelte library

| Piece | Where | What matters for this design |
|---|---|---|
| View state | `client_v2/src/lib/library/params.ts` | The whole view is the query string: `group`, `sort`, `dir`, `f` (filter chips), `arch`, `empty`, `page`, `size`, `sel`. `parseLibraryState` is a pure function of the URL; every mutator rewrites the query and calls `goto('?…')` *relative to the current path*, so the helpers work unchanged from any route. `replaceFilters` is this fork's one addition (Tier 2). |
| Layout preferences | `client_v2/src/lib/library/viewPrefs.ts`, `lib/stores/listWidth.svelte.ts`, `lib/stores/collapsedGroups.svelte.ts` | Things that are not "the view" live in `localStorage`, each in its own small store; `viewPrefs` and `listWidth` each have a parse function with a unit test (`collapsedGroups` has neither). Those two are the precedent for a fork preference store. |
| Page shell | `client_v2/src/routes/+page.svelte`, `+page.ts` | Splitter, list pane, `DetailPane` with `Inspector`. Untouched by this fork so far. |
| List | `client_v2/src/lib/components/library/FilamentList.svelte` | Fetches a page of groups or of spools, keeps its own live subscription, renders `ListToolbar`, then either `GroupRow` per group or `SpoolRow` per spool (line 140), then `Pagination` (line 161). Rows sit directly inside `<div class="groups scroll-y">`, a plain block container (its CSS sets only `flex: 1` on the element itself). |
| Group | `GroupRow.svelte` | Lazily loads its own window of spools and renders `SpoolRow` for used spools (line 185) and for single unused spools (line 190), `UnusedRow` for piles. |
| Pile | `UnusedRow.svelte` | Collapses identical never-used spools into one summary row; expanded, it renders `SpoolRow` again (line 110). |
| Row | `SpoolRow.svelte` | **An `<a href>`** (line 27) carrying `params.selectHref(...)`. Fixed columns: id, swatch, two-line name from `rowIdentity`, archived tag, `ProgressBar`, remaining, location. Props are `vm`, `showSwatch`, `indent`, `context` (lines 12-20). |
| Toolbar | `ListToolbar.svelte` | Filter chips, Group and Sort menus. This fork already owns a hunk here: `NlSearchButton` is imported at line 15 and mounted at line 399, and `DATE_FILTERS` is removed (#409). |
| Data layer | `client_v2/src/lib/api/spoolSource.ts`, `lib/stores/inventory.svelte.ts`, `lib/api/live.ts` | Per-spool write wrappers already exist: `saveSpool` (PATCH, line 401), `setSpoolArchived` (405), `useSpoolLength` (409), `useSpoolWeight` (416), `measureSpool` (423, `PUT /spool/{id}/measure`). Everything fetched is upserted into `inventory`; websocket events keep it current. |
| Single selection | `params.isSelected`, `?sel=kind:id` | There is no multi-select anywhere in the library components, no `Set` of ids, no checkbox column. |

Two facts constrain any design more than the rest:

1. **A checkbox cannot go inside the row.** The row is an anchor, and an `<input>` inside an
   `<a>` is invalid HTML. This fork already hit this on the low-stock page and solved it by making
   the checkbox a *sibling* of the row's link (`client_v2/src/routes/lowstock/+page.svelte`,
   the comment above the `rowItem` snippet, and the `.checkbox-slot` styles).
2. **Upstream's vendored Playwright suite finds spool rows by their link role.**
   `tests_frontend_v2/tests/crud.spec.ts:41`, `search.spec.ts:119`, `overrides.spec.ts:35` and
   others use `page.getByRole("link").filter({ hasText })` and then assert a `?sel=spool:` URL.
   That suite runs in CI (`tests-frontend-v2`) and gates releases (#399). Whatever the fork
   adds, the default DOM the suite sees must stay what upstream ships.

### 1.2 The React features, as they actually are

The issue's line references were checked; three details matter for the port.

| Feature | React source | What it really does |
|---|---|---|
| Gallery | `client/src/pages/spools/list.tsx:391` (`useSavedState("spoolList-viewMode")`), `spoolGalleryCard.tsx` | A CSS grid of cards over the same server-paged rows. A card is a large swatch, the filament's combined name, and "remaining · location". **No gauge, no actions, no selection.** Mode persists in `localStorage`, not the URL. |
| Bulk selection | `list.tsx:648-669` (bar), `:725-729` (`rowSelection`, `preserveSelectedRowKeys`) | Header checkbox selects the **current page**; selection survives paging and filter changes. The bar has exactly Edit, Archive-or-Unarchive (whichever the archived toggle makes possible), Clear. |
| Bulk edit | `client/src/pages/spools/bulkEdit.tsx:20,47-58` | Four fields: location, lot number, comment, price. A field is only sent if its checkbox is ticked; ticked-and-empty **clears** (`""` for text, `null` for price). Requests go through `client/src/utils/bulkPatch.ts:22-25`: one `PATCH /spool/{id}` per spool, `Promise.allSettled`, returns the failure count. The header comment there says why there is no bulk endpoint: `/api/v1` stays identical to upstream for Moonraker, OctoPrint and Home Assistant. |
| Weigh-in | `client/src/pages/spools/bulkWeightUpdate.tsx` | **Not selection-driven.** A toolbar button opens a search box; you pick one spool, enter length / used weight / measured gross weight (the same three modes as the per-spool Adjust dialog, same `PUT /spool/{id}/use` and `PUT /spool/{id}/measure`), press "Save & Next", repeat. Sequential, one request per save. It has no `catch`, so a failed save shows nothing. |
| Totals | `list.tsx:395-413,696-722` | Sums remaining weight, used weight and price (a spool with no price uses its filament's) over the **selection** if there is one, else over the **shown page**. Rendered as one spanning summary cell so column changes cannot break it. |
| Column manager | `client/src/components/columnManager.tsx`, `resizableHeaderCell.tsx`, `utils/saveload.ts:111-137`, `utils/columnOrder.ts` | Order, visibility and widths, each in its own `localStorage` key, `localStorage` only (never in the URL hash, unlike sorters and filters). Drag-reorder via `react-dnd`; resize by pointer drag on a header separator. |

So "bulk weigh-in over a selection" does not exist in React either. The issue and the Klipper
use-case both want it, and it is a strict improvement, so this design builds it that way and
treats React's search-then-save loop as a follow-up (open question 4).

### 1.3 What upstream is doing to these files

`git log upstream/master -30 -- client_v2/src/lib/components/library/` spans 2026-08-01 to
2026-08-23 (merges included). Counting which of those thirty touched each file, with the
file's last non-merge upstream commit:

| File | Commits in that window | Last non-merge commit |
|---|---|---|
| `ListToolbar.svelte` | 10 | 2026-08-19 |
| `SpoolInspector.svelte` | 7 | 2026-08-15 (`9ec5181d`, NFC tag linking) |
| `GroupRow.svelte` | 3 | 2026-08-19 |
| `GroupHeader.svelte` | 3 | 2026-08-19 |
| `UnusedRow.svelte` | 2 | 2026-08-18 |
| `SpoolRow.svelte` | 1 | 2026-08-18 (`713cb51f`, hover tooltips on truncation) |
| `FilamentList.svelte` | 0 | 2026-07-29 |
| `lib/library/params.ts` | 4 | 2026-08-19 |
| `routes/+page.svelte` | 1 | 2026-08-08 (list resizing; the remembered view landed the same day) |
| `components/Pagination.svelte` | 0 | 2026-07-29 |

Since the subtree base (`42721c7`) upstream has added three non-merge commits under
`client_v2/src` (`4c2febbb`, `eced7f22`, `035922b4`), all about NFC tags in the Add tag
dialog; none touch the library tree.

Upstream also has open feature requests for exactly this ground: **#1052 "Bulk edit"**, **#734
"Batch operations"**, **#768 "Gallery view"**. That is relevant to option C′ below, and it
means any design that edits `SpoolRow`, `GroupRow` or `ListToolbar` is betting against
upstream implementing the same feature in the same file within months.

### 1.4 Constraints every option shares

- **Strings.** Fork strings go in `client/public/locales/en/common.json`, their keys into
  `KEYS` in `scripts/build_ng_messages.mjs`, and the regenerated `client_v2/locales-ng/*.json`
  is committed (CI job `client-tests` fails on stale output). Components read them as
  `ng.spool_bulk_edit()` from `$lib/ng/i18n`; plurals via `plural()` there. The React catalogue
  already holds `spool.bulk.*`, `spool.totals.*`, `spool.view.*`, `spool.weigh.*` and
  `buttons.columns*`, so most of what these features say is already translated.
- **Unit tests** are vitest in `environment: 'node'` with no component testing library
  (`client_v2/vite.config.ts:27-33`). Anything worth a unit test has to be a plain `.ts`
  module, which is how every fork feature under `client_v2/src/lib/ng/` is built.
- **Browser tests** for fork-only Svelte behaviour go in `tests_frontend_ng/` (Playwright,
  REST seeding through `tests/helpers.ts`, backend on :8002 with
  `SPOOLMAN_LEGACY_CLIENT=FALSE`, see `.github/workflows/ci.yml` job `tests-frontend-ng`).
  Assertions go against the API (`spoolById`, `expect.poll`) rather than the DOM wherever a
  write is involved, per `TESTING_STRATEGY.md`.
- **No backend change is needed.** Every write these features make is a per-spool call the
  backend already serves and the Svelte data layer already wraps.
- **Named controls on a page upstream tests are a hazard** (see the settings-page note in the
  fork-additions doc): new `aria-label`s must not collide with labels upstream's specs query.

---

## 2. Options

Each option is described with the exact upstream-owned files it would edit, because that is
the cost this fork pays on every `git subtree pull`, forever.

### Option A — a fork-only alternate route (`/table`)

A new route directory, say `client_v2/src/routes/table/`, with its own `+page.ts` calling
`parseLibraryState` and its own page that renders a real table: selectable rows, a column
header row with reorder and resize, a totals footer, a gallery toggle. It reuses everything
below the rendering layer unchanged: `params.ts` (the mutators navigate relative to the
current path, so the same query grammar works on `/table`), `ListToolbar` imported as-is,
`spoolSource`, `inventory`, `live`, `Pagination`, `Inspector`, `DetailPane`, `Splitter`,
`Swatch`, `ProgressBar`.

| Upstream file edited | Edit | Cost |
|---|---|---|
| `src/lib/components/NavTabs.svelte` | one entry in `tabs` | Tier 1, already a fork-edited file; upstream last touched it 2026-07-30 |

That is the whole conflict surface: effectively zero.

What it costs instead:

- **Two libraries.** Every row-level refinement upstream makes (the August truncation
  tooltips, the override footnotes, whatever comes next) lands in the Library and not in the
  Table, and every fork feature has to decide which page it belongs to. The comparison doc
  already lists the React client as a parity backlog; this would create a second one inside
  the Svelte client.
- **Grouped mode.** The Library's grouping (`GroupRow`, `GroupHeader`, `UnusedRow`,
  `buildScopedSpoolQuery`) is half of the upstream library UI. A table route would either
  reimplement it or be flat-only, and a flat-only table cannot bulk-select "the six unused
  spools of this filament" without first filtering to it.
- **Discoverability.** Selection is a property of the list you are looking at. Sending the
  user to another tab to tick rows is the antd-era workflow the Svelte client was built to
  replace.
- **Search results and deep links** (`libraryHref`, `openSearchResult`, printed QR codes)
  all land on `/`, so selection state would be a page the user must remember to go to.

Right for the column manager, wrong for selection.

### Option B — a selection layer composed around `SpoolRow`, through an import seam

The natural version of this option wraps each `<SpoolRow …/>` in a fork component that adds a
sibling checkbox, and mounts a bulk bar and a toggle. Written naively that edits four template
sites (`FilamentList:140`, `GroupRow:185,190`, `UnusedRow:110`) plus the toolbar and the page,
in files upstream changes monthly.

The refinement that makes it cheap: **swap the import, not the usage.** In each of the three
files that render a spool row, the single line

```ts
import SpoolRow from './SpoolRow.svelte';
```

becomes

```ts
import SpoolRow from '$lib/ng/components/library/SpoolRow.svelte';
```

and the fork-owned `SpoolRow.svelte` is a thin wrapper:

```svelte
<script lang="ts">
	import type { ComponentProps } from 'svelte';
	import Upstream from '$components/library/SpoolRow.svelte';
	import { librarySelection } from '$lib/ng/librarySelection.svelte';
	let props: ComponentProps<typeof Upstream> = $props();
</script>

{#if librarySelection.mode === 'off'}
	<Upstream {...props} />
{:else}
	<div class="ng-row"><input type="checkbox" … /><Upstream {...props} /></div>
{/if}
```

Consequences:

- The template lines upstream edits (`<SpoolRow {vm} {showSwatch} indent={26} context={group.field} />`)
  are never touched, so upstream can add or rename props freely; `ComponentProps` forwards
  them. If upstream adds a fifth call site the fork's wrapper is not in it, which is a visible
  symptom (rows without checkboxes in one place) and a one-line fix.
- With selection off, the rendered DOM is byte-for-byte upstream's, so the vendored Playwright
  suite is unaffected. With selection on, the row is still the same `<a>` and the checkbox is a
  sibling, exactly the low-stock page's structure, so the suite's `getByRole("link")` queries
  still resolve.
- The same seam serves the gallery (the wrapper renders a card instead of a row) and, if ever
  wanted, custom columns (the wrapper renders its own cells). Neither needs a further mount.
- One more import swap, `Pagination` in `FilamentList`, gives the fork an in-flow footer under
  the list for the bulk bar and the totals: no fixed positioning, nothing hidden behind an
  overlay, works on the mobile sheet.

| Upstream file edited | Edit | Upstream commits to it, last 30 in the tree |
|---|---|---|
| `src/lib/components/library/FilamentList.svelte` | two import lines (`SpoolRow`, `Pagination`) | 0 (last 2026-07-29) |
| `src/lib/components/library/GroupRow.svelte` | one import line | 3 |
| `src/lib/components/library/UnusedRow.svelte` | one import line | 2 |
| `src/lib/components/library/ListToolbar.svelte` | one line, `<LibraryModeControls />`, on the line after the existing `<NlSearchButton />` mount | 10, but the hunk is already fork-owned, so this adds no new conflict site |

Five lines, four of them imports, the fifth inside a hunk the fork already re-applies. An import
line does conflict when upstream also edits the import block of that file (it did in `GroupRow`
on 2026-08-03), and resolving it is: keep both sides, keep the fork's path.

### Option C — extend upstream's row with optional slots or props

Give `SpoolRow` a `selectable`/`selected`/`ontoggle` prop set or a leading snippet, render the
checkbox inside the row's flex layout, add a selection bar to `FilamentList` and a toggle to
`ListToolbar`'s controls cluster, and render a bulk panel in `+page.svelte`'s detail pane.

| Upstream file edited | Edit | Upstream commits, last 30 |
|---|---|---|
| `SpoolRow.svelte` | props, markup, CSS; and the row would have to stop being an `<a>` or move the anchor inward | 1, but it is the file upstream refined twice in July too |
| `FilamentList.svelte`, `GroupRow.svelte`, `UnusedRow.svelte` | pass the new props at every call site | 0 / 3 / 2 |
| `ListToolbar.svelte` | a new control in `.controls` | 10 |
| `routes/+page.svelte` | `{#if}` around `Inspector`, `DetailPane` open condition | 1 |
| `src/lib/utils/library.ts` | if the VM grows a selection flag | 1 |

Seven files, real hunks in the two most active ones, and it changes the row's element type,
which the vendored suite would notice. This is exactly the case the fork-additions doc's
rule exists for: a changed line in a file upstream also changes costs a conflict on every
pull, and these are the files upstream changes most.

**C′ — do it upstream.** Upstream has #1052, #734 and #768 open. A slot on `SpoolRow` and a
selection store is a reasonable upstream PR, and if it lands the fork's mounts disappear at the
next subtree pull. Two reasons not to *wait* for it: upstream's cadence on the library tree is
one feature per week or two and none of the three requests has a design yet, and the fork's
Klipper users want the weigh-in flow now. The right sequencing is to build option B, then offer
upstream the selection store and the row seam as a PR against #1052 once it has had a release's
worth of use (open question 6).

### Summary

| | A: `/table` route | B: import seam | C: slots in upstream row |
|---|---|---|---|
| Upstream files edited | 1 (Tier 1) | 4 (5 lines) | 7 |
| Lines in actively edited hunks | 0 | 0 new | many |
| Vendored suite unaffected | yes | yes (identical DOM when off) | no |
| Selection where the user already is | no | yes | yes |
| Grouped mode covered | no, or duplicated | yes, for free | yes |
| Gallery | own grid | via the seam, no extra mount | edits `FilamentList` and `GroupRow` |
| Column manager | natural home | possible via the seam, flat only | edits `SpoolRow` heavily |
| Ongoing cost | second list to maintain | wrapper tracks upstream's props | merge conflicts every pull |

---

## 3. Recommendation

**Option B for selection, bulk edit and archive, weigh-in, gallery and totals, in that order;
the column manager last and only if still wanted after the rest has shipped.**

Reasons:

1. It puts selection on the rows users already look at, in both flat and grouped views,
   including the piles of identical unused spools, which is where "weigh these six" happens.
2. Its conflict surface is four import lines and one line the fork already owns. That is the
   same order of cost as the `NavTabs` entry, and it is the cheapest kind of conflict to
   resolve because both sides are always right.
3. Everything with judgement in it lives under `client_v2/src/lib/ng/`, where it is unit-tested
   the way the rest of the fork is, and the browser behaviour is covered in `tests_frontend_ng/`
   without touching the vendored suite.
4. The seam is reusable. Steps 3 to 5 add no further upstream edits.
5. It leaves the door open to C′ without depending on it.

The column manager is deliberately last: it is the only one of the four that turns the row
into something else entirely (a parallel cell renderer that stops inheriting upstream's row
work), it is the item users ask for least on this client, and this fork's `SpoolRow` already
adapts its columns to the group context (`rowIdentity`) in a way a manual column picker would
fight.

### 3.1 Steps

Each step is one PR. Each lists the fork-only files it adds, the upstream lines it touches, the
strings it needs, the tests it must carry, and the rows it appends to the Tier 2 table in
`docs/upstream/client-v2-fork-additions.md`.

Common to all fork Svelte files below: they live under `client_v2/src/lib/ng/components/library/`
(components) and `client_v2/src/lib/ng/` (logic, one `.test.ts` beside each `.ts`).

#### Step 1 — selection mode, bulk edit, bulk archive

*User value:* tick spools across pages and groups, change location / lot / price / comment on
all of them, archive or unarchive them. This is the piece everything else hangs off.

**Fork-only files**

| File | Role |
|---|---|
| `lib/ng/librarySelection.svelte.ts` | The store. `mode: 'off' \| 'on'`; `ids: SvelteSet<number>`; `snapshot: Map<number, SpoolVM>` captured at selection time (what React keeps in `selectedRecords`, so off-page spools still have a name and weights); a **registry** of currently rendered rows (`register(vm)` / `unregister(id)`, called by the row wrapper) so "select all shown" and the totals know what is on screen without touching `FilamentList`. `toggle(id)`, `selectShown()`, `clear()`, `setMode()`. Pure helpers (`selectionSummary`, `nextSnapshot`) in `librarySelection.ts` for unit tests. |
| `lib/ng/components/library/SpoolRow.svelte` | The seam described in §2 B. Renders upstream's row untouched when the mode is off; a `.ng-row` flex wrapper with a sibling `<input type="checkbox" aria-label="Select spool #{id}">` when on. Registers its `vm` while mounted. |
| `lib/ng/components/library/LibraryModeControls.svelte` | The "Select" chip, mounted in the toolbar's filter row beside `NlSearchButton`; while the mode is on it also shows "Select all shown", so selecting everything on screen does not require ticking one row first to make the bar appear. Step 3 adds the gallery toggle to it. |
| `lib/ng/components/library/LibraryFooter.svelte` | The `Pagination` seam: renders `<BulkBar />` (step 1), `<LibraryTotals />` (step 4), then upstream's `Pagination` with all props forwarded. |
| `lib/ng/components/library/BulkBar.svelte` | Hidden while nothing is selected. "N selected", Edit, Archive and/or Unarchive, Clear. Which archive button appears is decided by the selection snapshot, not by the view: Archive when any selected spool is active, Unarchive when any is archived, both when the selection mixes them. React derives it from its archived-only view; this client's toggle is `allowArchived` (`lib/api/query.ts`), which lists both kinds together, so a mixed selection is ordinary there rather than an edge case. |
| `lib/ng/components/library/BulkEditModal.svelte` | Four tick-to-change fields. Location is a text input with datalist from `spoolSource.locations()` so a new location can be typed. Uses upstream's `ConfirmDialog` conventions and the fork's conditional-mount pattern (`LoginModal`). |
| `lib/ng/bulkEditBody.ts` | `{ ticked, values } → SpoolPatch` with the ticked-empty-clears rule (`''` for text, `undefined`→`null` for price via `spoolPatchToApi`). Pure. |
| `lib/ng/bulkPatch.ts` | `bulkApply(ids, (id) => Promise<void>, { concurrency: 4 }) → { ok: number[], failed: { id, error }[] }`. Bounded concurrency rather than React's unbounded `allSettled`, because a 200-spool archive against SQLite should not open 200 requests at once. Callers pass `spoolSource.saveSpool` or `setSpoolArchived`, so the cache and the list update exactly as they do for a single edit. |

**Upstream lines touched**

| File | Line |
|---|---|
| `FilamentList.svelte` | `import SpoolRow from './SpoolRow.svelte'` → fork path; `import Pagination from '../Pagination.svelte'` → `$lib/ng/components/library/LibraryFooter.svelte` |
| `GroupRow.svelte` | `import SpoolRow …` → fork path |
| `UnusedRow.svelte` | `import SpoolRow …` → fork path |
| `ListToolbar.svelte` | `<LibraryModeControls />` on the line after `<NlSearchButton />` |

**Strings** (existing React keys reused unless marked new)

`spool.bulk.selected` (plural), `spool.bulk.edit`, `spool.bulk.clear_selection`,
`spool.bulk.edit_title` (plural), `spool.bulk.edit_help`, `spool.bulk.apply`,
`spool.bulk.nothing_selected`, `spool.bulk.applied` (plural), `spool.bulk.applied_partial`
(plural), `spool.bulk.archive_confirm` / `unarchive_confirm` (plural), `buttons.archive`,
`buttons.unArchive`, `buttons.cancel`, `spool.fields.location` / `lot_nr` / `price` / `comment`.
New: `spool.bulk.select_mode` ("Select"), `spool.bulk.select_shown` ("Select all shown"),
`spool.bulk.select_row` ("Select spool #{{id}}").

**Tests**

- vitest: `librarySelection.test.ts` (toggle, select-shown over a registry, clear, snapshot
  keeps an off-page spool's VM and a re-registered VM replaces it), `bulkEditBody.test.ts`
  (unticked fields absent; ticked empty clears; price `0` is a value, not a clear),
  `bulkPatch.test.ts` (failure count and ids with a fake writer; never more than `concurrency`
  in flight, asserted with a fake that counts overlap; empty id list makes no call).
- `tests_frontend_ng/tests/library-bulk.spec.ts`: seed three spools in one location (helpers
  `seedSpool`); with selection off, `getByRole('checkbox')` has count 0 and clicking a row
  still yields `?sel=spool:`; turn Select on, tick two, bulk-edit location, then
  `expect.poll(() => spoolById(...))` shows exactly those two moved and the third untouched;
  archive the two and they leave the default list and appear under the Archived chip, where
  the bar offers Unarchive for them; "Select all shown" with nothing ticked selects every
  seeded spool on the page; Clear empties the bar; grouped by filament, the checkboxes render
  under the group header.
- The vendored `tests_frontend_v2` suite must stay green, which is the proof that the default
  DOM is unchanged.

**Tier 2 rows to append:** one per upstream file above, each with "why it cannot be a new file":
the row and the pagination are instantiated inside upstream's list components and an import is
the smallest seam that reaches every instantiation.

**Hazards to write into the code**

- The wrapper styles upstream's `.row` through `:global(.ng-row > .row)` to drop its own
  `border-top` and let the wrapper carry the hairline. If upstream renames the class the
  symptom is a doubled hairline, not a broken page.
- A collapsed pile (`UnusedRow` not expanded) renders no `SpoolRow`, so its spools are not in
  the registry and "Select all shown" skips them. Expanding the pile is the way in. Adding a
  pile-level checkbox would mean editing `UnusedRow`'s template; not done (open question 3).
- Selection is in memory only, never `localStorage`: a selection restored days later is a
  destructive action waiting to happen. It survives paging, filter changes and opening the
  inspector; it is cleared by Clear, by a successful bulk apply, by turning the mode off, and
  by leaving the library route (the toolbar's controls unmount).

#### Step 2 — weigh-in over the selection

*User value:* after a print session, select the spools that were on the printer, put each on
the scale in turn, type the reading, next. One request per spool, no search box.

**Fork-only files**

| File | Role |
|---|---|
| `lib/ng/components/library/WeighInModal.svelte` | Steps through the selection in list order. Shows "3 of 12", the spool's identity (`rowIdentity(vm, 'flat')`), location, current remaining, one number input, the three-way mode (length / used weight / measured gross weight) read from and written to the same `spoolman-v2-adjust-mode` `localStorage` key the inspector's Adjust panel uses (`SpoolInspector.svelte`, `ADJUST_MODE_KEY`), so a mode picked in either place is what the other opens with. The key is a component-local constant there, not an export, so the fork duplicates the literal; see the hazard below. Buttons: Save & Next, Skip, Done. Ends on a per-spool result list. Enter submits. |
| `lib/ng/weighIn.ts` | The stepper as a pure reducer: `{ queue, index, results }` with `save(result)`, `skip()`, `done()`; validation identical to `applyAdjust` in the inspector (non-numeric refused, negative measured weight refused). The modal is the only caller. |

**Upstream lines touched:** none. `BulkBar` gains a "Weigh in" button.

**Strings**

Reused: `spool.weigh.title`, `spool.weigh.save_next`, `spool.weigh.done`, `spool.weigh.updated`,
`spool.form.measurement_type_label`, `spool.form.measurement_type.length` / `.weight`,
`spool.fields.measured_weight`, `spool.fields.remaining_weight`, `inspector.enterValidLength` /
`enterValidWeight` / `adjustFailed` (upstream keys, read through `m`). New: `spool.weigh.progress`
("{{index}} of {{count}}"), `spool.weigh.skip` ("Skip"), `spool.weigh.summary`
("{{updated}} updated, {{skipped}} skipped, {{failed}} failed"), `spool.bulk.weigh` ("Weigh in").

**Tests**

- vitest: `weighIn.test.ts` (order follows the queue; skip advances without a result; a failed
  save records the error and advances; done truncates; validation table matches the inspector's).
- `tests_frontend_ng/tests/library-weigh.spec.ts`: seed two spools whose filament has a known
  net `weight` and a known `spool_weight` (the helpers' `seedFilament` already sets one);
  select both; measured-weight mode; enter two gross readings; `expect.poll` on
  `GET /spool/{id}` shows `remaining_weight` equal to the hand-computed gross minus that
  filament tare for each (an independent oracle, per `TESTING_STRATEGY.md`). The tare the
  backend subtracts is the spool's own `spool_weight`, else the filament's, else nothing
  (`spoolman/database/spool.py`, `measure`); the vendor's empty-spool weight is only copied
  into a filament when the filament is created, so it must not be the oracle;
  a negative reading is refused client-side and no request is sent (`page.waitForRequest` with
  a short timeout that must not resolve); Skip leaves a spool unchanged.

**Tier 2 rows to append:** none.

**Hazard:** the shared `localStorage` key is a copied string. If upstream renames it the two
panels silently keep separate modes and nothing looks broken. Keep the literal in one fork
constant (`lib/ng/weighIn.ts`) with a unit test that reads `SpoolInspector.svelte` from disk
and asserts the string is still present, so a subtree pull that changes it fails `npm test`.

#### Step 3 — gallery view

*User value:* browse by colour. A card grid instead of rows, same paging, same filters, same
grouping.

**Fork-only files**

| File | Role |
|---|---|
| `lib/ng/libraryMode.svelte.ts` (+ `libraryMode.ts` for `parseStoredMode`) | `'list' \| 'gallery'` in `localStorage` key `spoolman-ng-library-mode`. A layout preference, not view state: the same category as list width and collapsed groups, so it stays out of the URL and out of `params.ts` (which would be a Tier 2 edit and would make every shared link carry a layout choice). |
| `lib/ng/components/library/SpoolCard.svelte` | Swatch at 56px, title and sub from `rowIdentity(vm, context)` so a card under a filament group does not repeat the filament, remaining weight, location, a thin `ProgressBar` along the bottom edge (the dashboard chip's gauge, `routes/dashboard/+page.svelte`, is the precedent), archived and low styling, the checkbox overlay in selection mode. The card is the same `<a href={selectHref}>` the row is. |

The seam wrapper renders `SpoolCard` when the mode is `gallery`. Cards are `display:
inline-flex; width: 168px; vertical-align: top`, so they flow and wrap inside upstream's
`.groups` block container and under each group header with **no change to `FilamentList` or
`GroupRow`**. `LibraryModeControls` gains the list/gallery toggle.

**Upstream lines touched:** none.

**Strings:** `spool.view.grid`, `spool.view.table`, `spool.view.grid_tooltip`,
`spool.view.table_tooltip` (all existing).

**Tests**

- vitest: `libraryMode.test.ts` (parse rejects junk, default is `list`, round-trip).
- `tests_frontend_ng/tests/library-gallery.spec.ts`: toggle to gallery, cards render one per
  seeded spool with `href` containing `sel=spool:`, clicking one opens the inspector; reload
  keeps gallery; grouped by material still shows the group header above the cards; back to
  list restores `.row` elements; selection mode works on cards.

**Tier 2 rows to append:** none.

**Hazard:** the inline flow depends on `.groups` being a block container. If upstream ever
makes it a flex column, cards stack one per line; the fix is one `:global(.groups)` rule in
the fork's wrapper, and the gallery spec catches it (assert cards share a row by comparing
bounding boxes).

#### Step 4 — totals row

*User value:* how much filament, how much used, how much money, for what is selected, else
for what is shown.

**Fork-only files**

| File | Role |
|---|---|
| `lib/ng/components/library/LibraryTotals.svelte` | Rendered by `LibraryFooter` above `Pagination`. One line: "12 spools selected · 4.2 kg remaining · 1.1 kg used · £180" or "20 spools shown · …". Uses `weightAuto` from `$lib/utils/format` and `settings.formatPrice` for the money, as the inspector does. |
| `lib/ng/libraryTotals.ts` | `totals(vms: SpoolVM[]) → { count, remaining, used, price }` with the price fallback `spool.price ?? filament.price`. Pure. |

Source of the numbers: the selection snapshot when there is one, else the registry of rendered
rows. In grouped mode "shown" means the rows currently loaded under expanded groups, which is
what is on screen; the per-group server aggregate in each header is a different number (the
whole group) and stays where it is. The `total` prop forwarded to `Pagination` is the
matching spool count only in flat mode; grouped, it counts groups (`FilamentList` passes
`unit={totalLabel}` for exactly this reason), so the footer shows "of N matching" in flat
mode and omits it when grouped.

**Upstream lines touched:** none.

**Strings:** `spool.totals.shown` / `spool.totals.selected` (plural, existing),
`spool.fields.remaining_weight` / `used_weight` / `price` (existing).

**Tests**

- vitest: `libraryTotals.test.ts` with hand-computed sums over a fixed dataset, including a
  spool without a price, an archived spool, and an unused spool.
- `tests_frontend_ng/tests/library-totals.spec.ts`: seed spools with known weights and prices;
  footer shows the expected line; select one and the label switches to "selected" with that
  spool's numbers; page size 1 shows a per-page "shown" figure.

**Tier 2 rows to append:** none.

#### Step 5 — column manager (optional, flat mode only)

*User value:* show lot numbers, prices or an extra field in the row; hide the location column;
widen the name. The least asked-for of the four on this client and the only one that stops
the row being upstream's row.

**Fork-only files**

| File | Role |
|---|---|
| `lib/ng/libraryColumns.svelte.ts` (+ `libraryColumns.ts`) | `{ order: string[], hidden: string[], widths: Record<string, number> }` in `localStorage` key `spoolman-ng-library-columns`; `effectiveOrder(saved, catalogue)` drops unknown ids and appends new ones (the React `computeEffectiveOrder` rule, re-specified by test not by copying). |
| `lib/ng/libraryColumnCatalogue.ts` | The column catalogue: id, swatch, name, material, vendor, diameter, remaining, used, progress, price, lot, location, first used, last used, registered, comment, plus `extra.<key>` from the `fields` store. |
| `lib/ng/components/library/ColumnManager.svelte` | A popover with a checkbox per column and up/down buttons for order (keyboard-operable; the extra-fields choice reorder upstream added to the React settings is the precedent for offering keys as well as drag). |
| `lib/ng/components/library/ColumnHeader.svelte` | A header row with pointer-drag resize handles (`role="separator"`, the `Splitter` component's pattern). |
| `lib/ng/components/library/SpoolCells.svelte` | The fork's own cell renderer, used by the seam **only when the stored config differs from the default**, so an untouched install keeps upstream's row and upstream's DOM. |

**Upstream lines touched:** one more import swap in `FilamentList.svelte`,
`import ListToolbar from './ListToolbar.svelte'` → a fork wrapper that renders upstream's
toolbar followed by `ColumnHeader` in flat mode. Grouped mode keeps upstream's rows: a header
row per group is not worth it and the group context already chooses the columns.

**Strings:** `buttons.columns`, `buttons.columnsTooltip` (existing); column labels come from
`spool.fields.*` and `filament.fields.*`, all existing. New: `spool.columns.reset` ("Reset
columns"), `spool.columns.move_up` / `move_down`.

**Tests:** vitest `libraryColumns.test.ts` (effective order rules, widths clamped to a minimum,
corrupt storage falls back); Playwright `library-columns.spec.ts` (hide a column and it leaves
the DOM; reorder persists across reload; reset restores upstream's `.row` markup; resize
changes the header cell width and the change survives reload).

**Tier 2 rows to append:** the `ListToolbar` import swap.

**Recommendation on this step:** do not schedule it. Ship steps 1 to 4, then ask in #412
whether anyone still wants it. The comparison doc sized it L for a reason, and that L now
includes maintaining a second row renderer against a row upstream keeps improving.

### 3.2 Order and why

1. **Selection + bulk edit + archive** first because nothing else works without the store and
   the seam, and because archive-many and relocate-many are daily chores.
2. **Weigh-in** second: it is the Klipper request, it needs only the store from step 1 and one
   modal, and it has the clearest test oracle (gross minus tare).
3. **Gallery** third: small, popular, and the seam is already in place so it costs nothing
   upstream-side.
4. **Totals** fourth: smallest, and it needs the registry from step 1 and the footer seam.
5. **Column manager** if at all.

### 3.3 What this design does not do

- It does not add a bulk endpoint. `/api/v1` stays byte-compatible with upstream, as React's
  `bulkPatch.ts` decided; the per-spool wrappers already exist and already update the cache.
- It does not put selection, layout mode or column config in the URL. Selection in a URL is a
  destructive action a bookmark can replay; layout mode and columns are preferences, and the
  URL is upstream's file (`params.ts`).
- It does not add inline cell editing. The issue mentions the panel-versus-inline trade-off;
  bulk edit closes most of the "many rows in succession" gap, and inline editing would mean
  the column-manager row renderer for every install. Left for a separate decision.
- It does not touch the filament list. React has a filament bulk edit; the Svelte library has
  no filament rows, only filament groups. Bulk-editing filaments would be a group-header
  selection, a different design.
- It does not edit `SpoolRow.svelte`, `GroupHeader.svelte`, `Inspector.svelte`,
  `routes/+page.svelte` or `params.ts`.

---

## 4. Open questions

Each with the answer this design assumes if nobody objects.

1. **Should the "Select" mode be a toggle, or should checkboxes always be present?**
   Default: a toggle. Always-on checkboxes cost 22px of every row in a client whose whole point
   is density, and the toggle is what keeps the default DOM identical to upstream's for the
   vendored suite.
2. **Should a selection survive leaving the library route?** Default: no. It survives paging,
   filtering and opening the inspector; navigating to another tab clears it. Persisting it is
   a footgun for the archive action.
3. **Should a collapsed pile of unused spools be selectable as one unit?** Default: no, expand
   the pile first. Doing it properly means a checkbox on `UnusedRow`'s summary row, which is an
   edit to a file upstream changed twice in August.
4. **Should the weigh-in also work with no selection, as React's search-then-save loop does?**
   Default: not in step 2. If wanted later it is a second entry into the same modal with a
   picker fed by `spoolSource.listSpools` and the fork's scanner hook (`ScanExtras`) so a QR
   scan can pick the next spool, which is the flow a workshop actually wants.
5. **Gallery in grouped mode: cards under headers (as designed) or flat only?** Default: under
   headers, because it costs nothing and grouping by material or manufacturer is where colour
   browsing is useful. Under a filament group every card is the same colour; that is true of
   the rows too.
6. **Offer the selection layer upstream?** Default: yes, after step 2 has been in a fork
   release: comment on Donkie/Spoolman#1052 with a link to this document and the store, and
   let upstream decide whether a slot on `SpoolRow` is wanted. Do not block on it.
7. **Totals over the whole filtered set rather than the shown page?** Default: no. The shown
   page mirrors React and needs no request; a whole-view figure would need a fork aggregate
   endpoint or a `listGroups` sum with a large limit, and the group headers already carry the
   per-group aggregates.
8. **Build the column manager at all?** Default: no, until steps 1 to 4 have shipped and
   someone asks in #412.
9. **Bounded concurrency of 4 for bulk writes?** Default: 4. SQLite serialises writes anyway;
   Postgres and MySQL installs would tolerate more, but the gain is invisible below a few
   hundred spools and the failure mode of "unbounded" is a stalled tab.
