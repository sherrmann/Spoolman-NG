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
