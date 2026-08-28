# Adding fork-only pages to the Svelte client

`client_v2/` is vendored from `Donkie/Spoolman` as a git subtree and pulled forward with

```
git subtree pull --prefix=client_v2 upstream master --squash
```

Upstream is active in that tree — a fetch on 2026-08-26 brought 290 commits touching it, most of
them Weblate translation churn under `client_v2/locales/`. So every file this fork edits inside
the subtree is a conflict this fork pays for on every pull, forever. The rule is therefore:

> **Add files. Do not edit files.** A new path upstream will never create costs nothing at pull
> time; a changed line in a file upstream also changes costs a conflict every time.

## What this fork adds (no conflict surface)

| Path | What |
|---|---|
| `client_v2/src/routes/home/` | Fork-only page routes, one directory each |
| `client_v2/src/lib/ng/` | Fork-only logic, types, API access and message helpers |
| `client_v2/project-ng.inlang/` | The fork's own inlang project and its generated messages |

## What this fork edits, and why each is unavoidable

Two tiers, and the difference matters when a pull conflicts.

**Tier 1 — plumbing.** Five files, all additive, all small — three of them one-line entries in
tool config. Re-apply the fork side and move on.

| File | Edit | Why it cannot be a new file |
|---|---|---|
| `vite.config.ts` | A second `paraglideVitePlugin({ project: './project-ng.inlang' })` | Vite reads exactly one config; a plugin cannot register itself |
| `package.json` | `paraglide` also runs `paraglide:ng` | `npm run check` compiles messages before typechecking, and CI runs it |
| `src/lib/components/NavTabs.svelte` | One entry per fork page in the `tabs` array | It is the single source of truth for the nav, on both desktop and mobile |
| `.prettierignore` | `src/lib/paraglide-ng` and the `project-ng.inlang` generated files | Tool config is one file; the entries sit directly beside upstream's own for `src/lib/paraglide` and `project.inlang` |
| `eslint.config.js` | `src/lib/paraglide-ng/` and `project-ng.inlang/` in `ignores` | Same reason, beside the same upstream entries |

Every one of the last two is a copy of a line upstream already wrote for its own generated i18n
output, with `-ng` appended — which is also what makes them cheap to re-apply after a conflict.

**Tier 2 — deliberate edits inside pages upstream actively develops.** These are not plumbing and
they are not cheap: upstream is still changing these files, so expect real conflicts and expect to
have to understand both sides. Each one is here because a fork feature has to live *inside* an
upstream page rather than beside it.

| File | Edit | Why it cannot be a new file |
|---|---|---|
| `src/routes/dashboard/+page.svelte` | A remaining-weight gauge on the spool chip (`.chip-gauge`, `gaugeColor()`, and the `getWeightPct` import) | `/dashboard` **is** this fork's locations board — upstream's page replaced the React one — and the gauge belongs on its chips. A separate board would duplicate a live upstream page |
| `src/lib/labels/types.ts` | `'location'` in `LabelKind`, `DEFAULT_LOCATION_TEXT`, four `DEFAULT_TEXT_PAIRS` entries, `defaultTextTemplate` as a switch | The kind union is the seam the whole feature hangs off |
| `src/lib/labels/qr.ts` | `showPath` → `location`, `schemePrefix` → `L` | The `L-<id>` scheme and `/location/show/<id>` URL are what this fork's React client already prints |
| `src/lib/labels/template.ts` | `LabelBinding.location`, four resolvers, the extra-field regex, a `location` palette group, `PlaceholderEntity`, per-kind palette filtering | Resolvers and the palette are one table each |
| `src/lib/labels/render.ts`, `print.ts` | Three-way subject id and export filename | Both were two-way ternaries |
| `src/lib/components/labels/LabelDesigner.svelte` | Loads location field defs via `listLocationFields()` | The `fields` store is typed to upstream's `EntityType` and cannot be asked for `location` |
| `src/lib/components/labels/PrintLayoutPanel.svelte` | A third subject-selection path beside the spool and filament ones | Each kind's picker is written out in this one component |
| `src/routes/labels/+page.svelte` | A third label-type button, and a location-specific hint | The segmented control is one element |
| `src/lib/utils/spoolCode.ts` | `l`/`location` in both scan regexes, `ScannedRef.kind`, `normaliseKind` as a switch | The scanner's parser is one module, and printing a code the client then ignores is not a feature |
| `src/lib/components/QrScannerModal.svelte` | A scanned location goes to `/location/show/<id>`; and each decode is offered to `$lib/ng/components/ScanExtras` before upstream's own handling | The scanner has one decode callback. The delegation is three lines and deliberately *declines* an ordinary entity scan, so upstream keeps owning navigation and keeps owning it after it changes |
| `src/lib/library/params.ts` | One export, `replaceFilters` | A natural-language search produces a whole view at once. Applying it through the existing per-filter mutators would push several entries onto the history stack, so Back would walk through states the user never asked for |
| `src/lib/components/library/ListToolbar.svelte` | `<NlSearchButton />` beside the filter chips | The button's whole point is that it fills these chips in; anywhere else and it reads as a separate search |
| `src/routes/settings/+page.svelte` | `<AiSettings />`. **Adding named controls to a vendored page is a hazard**: upstream's own specs query labels page-wide, so a field announced the same as one already there takes their query from one match to several and fails it. The AI panel's two URL fields are therefore announced as "AI endpoint URL" and "Transcription endpoint URL", not by their visible row titles. Check `getByLabel` names in `tests_frontend_v2` before adding a control to a page upstream tests | The assistant's configuration belongs on the settings page. Renders nothing for a non-administrator |
| `src/routes/+layout.svelte` | `<AiChatLauncher />`, one element | The assistant is global, not a page. It renders nothing at all unless the operator has enabled it, so the cost when off is one settings read |
| `src/lib/components/TagsSection.svelte` | An "Encode to NFC" action beside upstream's "Add tag", and the fork's `NfcWriteModal` mounted from it | This section IS the spool's tag UI. Upstream links a tag by its UID and never reads or writes what is stored on it, so writing a spool's data onto one has no home of its own; a separate section for one button would read as a different feature |
| `src/lib/components/AddSpoolModal.svelte`, `src/lib/stores/ui.svelte.ts`, `src/routes/+layout.svelte` | A third preset, `presetArticleNumber`, beside the existing `presetFilamentId` and `duplicateFilamentId` | A scanned retail barcode no filament claims (#97b) must open a new-filament form carrying it. This is upstream's own preset mechanism with one more entry, written in the same three places the other two are |
| `src/lib/components/library/FilamentInspector.svelte` | One icon-button linking to `/calibration?filament=<id>` | Calibration belongs to a filament, and this panel is where a filament is looked at. React reaches it as a tab on `/filament/show/:id`; this client has no such page — that route is a redirect and this inspector has no tab strip |

Two hazards specific to that page, both found by measuring rather than reading:

- `.chip` needed `overflow: hidden` to clip the gauge to its corners, and that changes the flex
  item's automatic minimum size from its content height to **zero** (`min-height: auto` applies
  only while `overflow` is `visible`). Chips in a card holding more than its `max-height` then
  shrank instead of the body scrolling — 41px to 21px, text clipped mid-line. `flex: none`
  restores what `min-height: auto` was doing implicitly. If a pull ever drops that line, the
  symptom is crushed chips in the fullest card only.
- `CHIP_H = 44` near the top of that file is measured from the `.chip` CSS and feeds
  `bodyReserve()`, which reserves each card's height before its spools load. Anything added to a
  chip must not change its height — which is why the gauge is absolutely positioned along the
  bottom edge rather than added as a row.

And one about the label designer, worth knowing before touching it:

- **Widening `LabelKind` only fails the build in one place.** `DEFAULT_TEXT_PAIRS` is typed
  `Record<LabelKind, string>[]`, so it stops compiling — but four *ternaries* keyed on the kind
  (`qr.ts` ×2, `render.ts`, `print.ts`) stayed silent, each meaning "spool" for anything that
  isn't `'filament'`. Left alone they would have printed a spool QR on a location label and named
  its export `spoolman-location-label-undefined`. All four are switches now; keep them that way.
And one about the filament inspector:

- It is a **flat panel, not a tabbed page**, which is why calibration lives on its own route
  with only a link from here. Do not be tempted to grow a tab strip in it to mirror the React
  client — that would be a large edit to a file upstream actively develops, to host a feature
  that works perfectly well beside it. If upstream ever adds tabs of its own, revisit.

- `setDesignKind` retargets text templates and never adds or removes elements, which is upstream's
  deliberate choice. A default design switched to `location` therefore keeps its colour swatch,
  which a location cannot fill. Left as-is: dropping elements on a kind switch would destroy work
  a user may have kept on purpose. `src/lib/ng/labelLocation.test.ts` (fork-owned, deliberately
  outside the vendored tree) pins the QR payloads and the retargeting.

`client_v2/locales-ng/` deliberately does **not** need a `.prettierignore` entry: the generator
emits tab-indented JSON to match the client's `useTabs` config, so the generated catalogue passes
`prettier --check` as written.

## Why fork strings are not in `client_v2/locales/`

That directory is Weblate's. Putting fork keys there means a conflict on most pulls and a fresh
translation effort for strings this fork already has in 32 languages.

Instead `scripts/build_ng_messages.mjs` transcribes the keys the Svelte pages need out of the
React client's existing catalogue (`client/public/locales/{locale}/common.json`) into
`client_v2/locales-ng/{locale}.json`, and a second Paraglide instance compiles
those to `src/lib/paraglide-ng/`.

The transcription exists for a specific reason rather than tidiness. Pointing inlang's i18next
plugin straight at the React catalogue does work, but that plugin reads an underscore in a key
as i18next's *context* separator: `home.total_weight` and `home.total_value` collapse into one
`home.total` message taking `{ context: 'weight' | 'value' }`, and a call that guesses the split
wrong renders the raw key instead of failing the build. Measured against the keys these pages
need, **29 of 51 keys were re-split that way** — including `low_stock.title`, where the
underscore is in the namespace. `@inlang/plugin-message-format` treats ids as opaque, so the
generated project has none of that behaviour.

Both Paraglide runtimes use the same `PARAGLIDE_LOCALE` localStorage key, and the language
picker in `settings/+page.svelte` calls `setLocale()` with its default options, which reloads
the page. So switching language moves both catalogues together with no coordination code.

### Changing or adding a string

1. Edit the React catalogue (`client/public/locales/en/common.json`) — it stays the source of
   truth, so the two clients cannot disagree about what a label says.
2. Add the key to `KEYS` in `scripts/build_ng_messages.mjs` if it is new.
3. Run `node scripts/build_ng_messages.mjs` and commit the regenerated messages.

CI re-runs the generator and fails if the working tree comes back dirty, so the committed output
cannot drift from the catalogue it was built from.

## `npm run build` dirties the vendored tree — do not commit that

Upstream's own `prebuild` hook runs `client_v2/scripts/strip-empty-locales.mjs`, which rewrites
`client_v2/locales/*/common.json` in place to drop the empty-string placeholders Weblate leaves
behind for untranslated keys. A local build therefore leaves 24 vendored files modified with
several thousand deleted lines, and a reflexive `git commit -a` would quietly turn that into a
permanent divergence from upstream — the worst possible edit to the one directory Weblate
rewrites most.

After building, discard it:

```
git checkout -- client_v2/locales
```

The generator's own CI freshness check is scoped to `client_v2/locales-ng`
precisely so this unrelated churn cannot make it fail.
