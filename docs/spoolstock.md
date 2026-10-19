# Moving from Spoolstock

Spoolman NG can read a Spoolstock CSV export and bring its spools in, with their filaments and
manufacturers (#436).

## Import the file

Export your inventory from Spoolstock as CSV, then send it to `POST /api/v1/import/spoolstock`.
Try it first with `dry_run=true`, which reports what would be created and writes nothing:

```sh
curl -X POST --data-binary @spoolstock.csv \
     "http://localhost:7912/api/v1/import/spoolstock?dry_run=true"
```

When the counts look right, send the same request without `dry_run`. If `SPOOLMAN_API_TOKEN` is set,
or accounts are enabled, add `-H "Authorization: Bearer <your token>"`; importing needs an account
that may make changes.

The answer lists how many manufacturers, filaments and spools were created, how many filaments you
already had were used, how many spools were skipped, and any errors. The import is all or
nothing: if one row cannot be read, nothing is written and the errors say which rows, numbered as
in a spreadsheet (the header is row 1).

## What goes where

| Spoolstock column | Spoolman NG |
|---|---|
| `filament.brand.name` | Manufacturer (matched by name, ignoring case and leading or trailing spaces; "Unknown" when empty) |
| `filament.name` | Filament name |
| `filament.material.name` | Material |
| `filament.material.density` | Density |
| `diameter`, else `filament.diameter` | Diameter (1.75 mm when neither is given) |
| `size` | Filament weight, and the spool's initial weight (the remaining weight when there is no size) |
| `empty_spool.weight` | Empty spool weight, on the filament and the spool |
| `filament.color_hex_codes` | Colour; several codes make a multi-colour filament |
| `filament.material.low_temp` / `high_temp` | Recommended nozzle temperature range, and the middle of it as the nozzle temperature |
| `filament.material.low_bed_temp` / `high_bed_temp` | Recommended bed temperature range, and the middle of it as the bed temperature |
| `filament.upc` | Article number |
| `filament.notes`, `filament.product_family`, `filament.repurchase_url` | Filament comment |
| `remaining_weight` | The spool's used weight is the initial weight minus this |
| `price` | Spool price |
| `depleted` | Archived |
| `notes`, `purchase_source`, `purchased_on` | Spool comment |
| `short_id` | Kept in the spool comment as `Spoolstock ID: …` |

Other columns (ratings, favourites, totals Spoolstock calculates) are not imported.

## Things to know

- **Existing records are reused.** A manufacturer you already have is used as it is. A filament is
  reused when manufacturer, name, material, diameter and weight all match; otherwise a new one is
  created. Spools are always new.
- **Importing again is safe.** Each spool remembers its Spoolstock id, and a second import of the same
  file skips the spools already brought in. Spools you added in Spoolstock since are created. A
  spool that appears twice in one file is imported once.
- **Implausible values are refused.** A temperature above 1000 °C, a range whose low end is above
  its high end, or a weight, price, density or diameter above a billion makes that row an error.
- **Density.** Spoolman needs a density for every filament. When a row has none, the value from the
  SpoolmanDB catalogue is used if the catalogue has been downloaded (it is, after the first sync on a
  server with internet access); otherwise that row is reported as an error.
- **Multi-colour filaments** are created as side-by-side (coaxial) colours, since Spoolstock does not
  say how the colours run; change it on the filament if the colours run along the strand.
- **Thousands separators** are not guessed at: a weight written as `1,000` is left out, and the row
  imports without it. Spoolstock writes plain numbers, so this only matters for a file edited in a
  spreadsheet.

There is no button for this in the interface yet; use the request above.
