# Import, export and the 3MF matcher in the Svelte client (#414)

Status: step 1 built; step 2 designed.

#414 lists two settings features the frozen React client has and `client_v2` lacks. The backend for
both exists and needs no change. The rule from
[`client-v2-fork-additions.md`](../upstream/client-v2-fork-additions.md) applies: new files under
`client_v2/src/lib/ng/`, no edits to upstream files.

## 1. What exists

**Backend.**

- `GET /export/{spools,filaments,vendors}?fmt=csv|json` returns a file download
  (`Content-Disposition: attachment`). Rows are flattened (`filament.vendor.name`,
  `extra.<key>`), CSV cells that start with `= + - @` are escaped, and archived spools are left
  out unless `allow_archived=true`.
- `POST /import/{vendor,filament,spool}?fmt=&mode=create|upsert|skip_existing&dry_run=` takes
  the raw CSV or JSON as the body, in the shape the export produces. It returns
  `{created, updated, skipped, dry_run, errors: string[]}`, one string per bad row.
- Matching is by `id` only. `create` ignores the id; `upsert` updates the row with that id or
  inserts; `skip_existing` counts it as skipped.
- A file with any bad row writes nothing: the whole import is rolled back. A dry run always
  rolls back, but reports the counts it would have applied.
- Auth: the middleware lets a read-only user make GET requests only. So **export is open to
  every signed-in user**; **import is administrators only**. The 3MF matcher records usage with
  `PUT /spool/{id}/use`, so it is administrators only too.

**Classic client.** One settings tab with:

- export buttons (CSV and JSON per entity)
- an import form: entity, format, mode, dry-run checkbox, file picker, and a result toast
  showing the counts and the first three errors
- a "Print report" button: all non-archived spools, a summary (count, remaining weight, value)
  and a table by material, printed with the browser's print dialog
- the 3MF matcher, nested in the same tab

**Svelte client.** None of it exists. What it already has:

- `listAllSpools`, `listAllFilaments` and the analytics helpers the home page uses
  (`materialBreakdown`, `totalRemainingWeight`, `totalValue`), which cover the report's numbers
- `spoolSource.useSpoolWeight`, the `/use` call the matcher needs
- the label designer's print technique (a print-only root and `@media print` CSS)
- `fflate`, for reading a 3MF

## 2. Where it goes

One **Import & export** section, mounted through the fork's `NgSettings` like the other fork
panels. That means no edit to upstream's settings page.

Unlike the other panels, it is **not** hidden from non-administrators, since export and the
report are theirs to use too. The import form and the 3MF matcher render only for administrators.

Downloads cannot be plain links. The bearer token lives in localStorage, not a cookie, so an
`<a href>` to `/export/...` would be refused on an authenticated install. The file is fetched
with the token and saved from a blob, as the photo and swatch code already do.

## 3. Steps

### Step 1: export, import, report

- **Export:** a row per entity (spools, filaments, manufacturers), each with CSV and JSON.
- **Import:**
  - entity, mode and a dry-run checkbox, which is on by default. A first run that only
    validates is the safe habit, and the classic client leaves it off.
  - The format is taken from the file's extension and can be changed.
  - The result stays on the page rather than in a toast that vanishes. It shows the counts, and
    every error in a scrollable list rather than only the first three.
  - Lists already on screen elsewhere are not refreshed: the server writes imported rows without
    broadcasting them. The Library loads fresh lists when opened, which is where they are seen.
  - The three selects are named "Data", "Mode" and "Format". The classic client had no labels
    for them, so these three strings are new in its catalogue (English only for now).
- **Report:** a "Print report" button that loads the spools and filaments, builds the report in a
  print-only root, and opens the print dialog. It shows the date, the spool count, the remaining
  weight, the value and the by-material table.

The logic that is not UI (filename, format from extension, the import request, report rows) goes
in `lib/ng/importExport.ts` with unit tests.

### Step 2: the 3MF slice-import matcher

- `client/src/utils/threeMfImport.ts` (98 lines, framework-free) and its tests are copied to
  `lib/ng/`. The only change is the spool type it reads.
  - It reads Bambu Studio / OrcaSlicer's `Metadata/slice_info.config` and sums grams per
    filament across plates.
  - Its matching: the same colour exactly, then the same material. It has no nearest-colour
    matching.
- The parser uses `DOMParser`, which the browser has but the client's node test environment
  does not. The tests install a DOMParser shim built on the swatch port's strict test parser
  (`lib/ng/swatch/xmlTestHelpers.ts`), rather than a new dependency.
- UI: a file picker, then one row per filament used, showing its swatch, material and grams, and
  a spool picker pre-filled by the matcher. An "Apply" button records each row's usage in turn
  and reports how many succeeded.

## 4. Open questions

Each with the answer this design assumes if nobody objects.

1. **Dry run on by default?** Default: yes (see step 1).
2. **Export archived spools?** Default: no, as in the classic client and the server's default.
   A checkbox would be one line if asked for.
3. **PrusaSlicer 3MF files in the matcher?** Default: not now. The classic client supports
   Bambu/Orca only, and so will the port; the error message says so.
