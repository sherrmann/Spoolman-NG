# Filament parity in the Svelte client (#415)

Status: all three steps built.

#415 lists five filament features the frozen React client has and `client_v2` lacks. This note
records where each one attaches to the vendored client, in the order they are built. The rule
from [`client-v2-fork-additions.md`](../upstream/client-v2-fork-additions.md) applies throughout:
add files under `client_v2/src/lib/ng/`, and edit an upstream file only by a line or two, recorded
as Tier 2.

## 1. What exists

**Backend (complete for all five).**

- Catalogue fields (#91): `spool_type` (`plastic`, `cardboard`, `metal`), `finish` (`matte`,
  `glossy`), `pattern` (`marble`, `sparkle`), `translucent` and `glow` (booleans). All nullable;
  null means unknown. The API validates the three enums; the columns are plain strings.
  SpoolmanDB carries all five (`spoolman/externaldb.py`, `ExternalFilament`), and
  `/external/filament/search` returns them.
- Per-filament stock: `remaining_weight` and `spool_count` on the filament list and detail
  responses, summed over non-archived spools.
- `swatch_style` setting: a JSON-encoded string, default `""`, meaning the `classic` style.
- Reference images: `GET`/`PUT`/`DELETE /filament/{id}/image`, JPEG, PNG or WebP up to 2 MiB,
  with an `ETag` and `If-None-Match` support. `has_image` on the filament. The server does no
  image processing; the React client resizes to 1024 px and re-encodes to WebP first.

**React client.** Catalogue fields as five clearable selects on the create and edit forms and as
opt-in list columns; the stock column; a swatch-style settings tab with a live preview; a 3MF
"swatch" download (a printable colour sample card with the filament's name and a QR code); image
upload and display.

**Svelte client.**

- Its `Filament` view model (`lib/types.ts`, filled by `mapFilament` in `lib/api/map.ts`) has
  none of the catalogue fields, no `has_image`, no stock aggregate.
- **Bug:** `spoolSource.importExternalFilament` builds the create body field by field and leaves
  the five catalogue fields out, so a filament imported from SpoolmanDB through this client
  loses them. The React client copies them (`client/src/pages/filaments/create.tsx`).
- Stock per filament is **already shown**, in another form: grouping the library by filament
  puts each filament's total remaining weight in its group row (`GroupRow.svelte`), and the
  filament inspector's header shows the same total (#572). The React list column has no further
  equivalent to build here; #415's second item is closed by pointing at those.

## 2. The seam

The catalogue fields are data on the filament, so they belong in the view model, where the
cache, live updates and the save path already carry everything else. Keeping them out of it
(a fork component fetching `GET /filament/{id}` itself) would mean a second copy of the filament
that live updates do not refresh, and a second save path.

So the view model gets **one optional, fork-owned property**, and each upstream function that
maps a filament gets **one line** that hands over to fork code:

| Upstream file | Edit |
|---|---|
| `lib/types.ts` | `ng?: FilamentNg` on `Filament`, with a type-only import |
| `lib/api/map.ts` | `ng: mapFilamentNg(f)` in `mapFilament`; `Object.assign(out, filamentNgPatchToApi(patch))` in `filamentPatchToApi` |
| `lib/api/spoolSource.ts` | `...catalogueFromExternal(ext)` in `importExternalFilament`'s create body |
| `components/library/FilamentInspector.svelte` | one import and `<FilamentCatalogueFields {filament} />` inside the specs grid |

Everything else is in `lib/ng/filamentCatalogue.ts` (types, option lists, mapping both ways,
tested) and `lib/ng/components/FilamentCatalogueFields.svelte`.

`ng` keeps the fork's fields in one place: a later upstream field of the same name cannot
collide with them, and a pull that changes `mapFilament` conflicts on one line at most.

Steps 2 and 3 add to the same `FilamentNg` (`hasImage`) and the same inspector, so they do not
widen the seam further than one more line each.

## 3. Steps

### Step 1: catalogue fields, and the import fix

- `FilamentNg` = `{ spoolType, finish, pattern, translucent, glow }`, each `null` when unknown.
- The inspector shows five rows in its specs grid, after the article number: three selects with
  an empty "unknown" choice, and two for translucent and glow with unknown, yes and no. The
  booleans are three-way because the database has three states, and "no" is information
  ("not translucent") that the empty state is not.
- Saved through a debounced saver of the component's own, keyed by field, so only the fields
  edited are sent. Not the inspector's saver: it merges a pending patch one level deep, so a
  whole `ng` object replaced the previous one, and a live update landing between two quick edits
  (a spool event carries its filament) sent the first field back to its old value.
- `importExternalFilament` copies the catalogue entry's spool type, finish and pattern, and
  translucent and glow only when true. The catalogue's model defaults both booleans to `false`
  and TigerTag entries leave them out, so a `false` there cannot be told from "not recorded";
  storing it would claim "no" where nothing is known. The React client does the same.
- The library's column manager (#456) gets five columns, hidden by default, like every column
  beyond upstream's row.
- **Added after step 3:** the fields on the new-filament form, and carried by duplicate (open
  question 1, answered yes). The five choices sit in the form's "Advanced specs" block, drawn by
  the fork's `NewFilamentCatalogueFields.svelte` and written into the draft under `ng`, so the
  add-spools flow and the change-filament dialog both get them. A duplicate copies all five from
  its source, as the React client's clone does; that includes "Add & new", which starts from the
  filament just created. On create, unknown is left out of the body and `false` is sent: unlike
  a catalogue import, a `false` here was chosen or copied from a stored value. The upstream
  edits are one-line seams in `lib/filament/draft.ts` (four), `lib/api/spoolSource.ts` (three)
  and `NewFilamentCards.svelte` (two), listed in the fork-additions ledger.

### Step 2: reference images

As built: `lib/ng/filamentImage.ts` (preparation, fetch, upload, delete) and
`lib/ng/components/FilamentImageSection.svelte`; the inspector gains one import and one line.

- `hasImage` in `FilamentNg`, read-only there: `filamentNgPatchToApi` never sends it.
- A fork `FilamentImage` section in the inspector's right-hand column, under the manufacturer,
  showing the image with replace and remove, or an upload button when there is none.
- Fetched with the client's credentials (a bearer token, not a cookie, so `<img src>` does not
  work) into an object URL, with the `ETag` kept to revalidate. Uploads go through a port of the
  React client's `imageTransform.ts`: EXIF rotation applied, longest side at most 1024 px, WebP
  (JPEG where the browser cannot encode WebP).
- Upload and removal save at once, not through a debounced saver: the photo has its own
  endpoints. Both endpoints broadcast a filament update, so another open client learns that a
  photo was added or removed. A photo **replaced** elsewhere keeps `has_image` true, so it shows
  the next time that filament is opened, when the cached copy is revalidated. Revalidating on
  every filament update instead would mean a request per spool event during a print.
- Not on the new-filament form: the photo endpoints take a filament id, so a photo is added in
  the inspector once the filament exists.

### Step 3: swatch style and 3MF swatch download

The style setting only affects the download, so they go together.

As built: the generator is in `lib/ng/swatch/`; the dialog, the inspector icon, the preview and
the settings panel are in `lib/ng/components/swatch/`. The settings panel mounts through the
fork's `NgSettings`, so upstream's settings page is not touched again; the inspector gains one
import and one line. Checked against the classic client: with the same QR matrix, every file in
the 3MF is identical for all five styles. The QR matrices themselves differ, because `qrcode`
and `qrcode-generator` choose different masks; each of the port's codes was decoded back to its
payload with zxing. The classic tests that parse the 3MF's XML used the browser's `DOMParser`,
which the client's node test environment lacks; they run against a small test-only parser
(`xmlTestHelpers.ts`) rather than a new dependency. It throws where DOMParser would report a
parse error (mismatched or unclosed tags, an unescaped `&` or `<`), so a broken escape still
fails the escaping test.

Known limitation, shared with the label designer and the classic client: the link form of the
QR code is `<base URL setting>/filament/show/<id>`, or the page's origin when that setting is
empty. Under a sub-path deployment with no base URL set, the origin lacks the path prefix and
the link does not resolve. Fixing it belongs in one place for all three, not in the swatch.

- `client/src/utils/swatch/*.ts` (about 1,250 lines, framework-free) and its tests are copied to
  `lib/ng/swatch/`. The one change: its QR module uses `qrcode-generator`, which `client_v2`
  does not have; it is rewritten against `qrcode`, which `client_v2` already uses, rather than
  adding a dependency to upstream's `package.json`. The test pins the QR matrix, so a
  difference would fail the test.
- A "Download swatch" icon button in the inspector header, beside duplicate and delete, opening
  a dialog like the React one: style (defaulting to the setting), QR as scan code or URL, and
  download.
- The setting as a section of the settings page, among the fork's other panels, with the
  two-sample preview. Administrators only, like those panels, since the write needs admin
  rights.

## 4. Open questions

Each with the answer this design assumes if nobody objects.

1. **Catalogue fields on the new-filament form, and carried by duplicate?** Answered yes, and
   built (step 1 above).
2. **Filter the library by the catalogue fields?** Default: no. Upstream's filter menu reads
   upstream's field list; adding to it is a larger edit than any of these steps, and nobody has
   asked for it.
3. **Show the image anywhere but the inspector (a library column, the gallery card)?** Default:
   no. Every image costs an authenticated request, and the gallery is about colour.
