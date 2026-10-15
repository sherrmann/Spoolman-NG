# SimplyPrint export

Spoolman NG can write your spools as a file that SimplyPrint's Filament Manager imports (#312).
It is a **one-way, one-off copy**: it puts today's spools into SimplyPrint, and nothing flows
back or stays in sync.

The format follows SimplyPrint's own exporter,
[`spoolman-export.py`](https://cdn.simplyprint.io/downloads/tools/spoolman-export.py), which is
the reference for the field names and their order. The code in Spoolman NG is written
independently; only the format is shared.

## Download the file

`GET /api/v1/export/simplyprint` returns a JSON array and offers it as a download named
`spoolman-export.json`. Any signed-in user may call it, including read-only ones.

```sh
curl -o spoolman-export.json http://localhost:7912/api/v1/export/simplyprint
```

If `SPOOLMAN_API_TOKEN` is set, or accounts are enabled, send the token as a bearer header:

```sh
curl -H "Authorization: Bearer <your token>" \
     -o spoolman-export.json http://localhost:7912/api/v1/export/simplyprint
```

Then upload `spoolman-export.json` in SimplyPrint's Filament Manager import. According to
[SimplyPrint's help article](https://help.simplyprint.io/en/article/how-to-export-your-filament-spools-from-spoolman-import-into-simplyprint-e61m3y/),
the filament import is part of its Pro plan.

## Fields

Each spool becomes one object with these keys, in this order:

| Key | Taken from |
|---|---|
| `spoolman_spool_id` | The spool's ID |
| `brand` | The manufacturer's name; an empty string when the filament has none |
| `material` | The filament's material |
| `filament_name` | The filament's name |
| `color_hex` | The filament's colour as 6 or 8 hex digits, without `#`; empty when it has no single colour |
| `width` | The spool's measured diameter if it has one, otherwise the filament's diameter (mm); 1.75 when neither is known |
| `total_weight_grams` | The spool's initial weight, otherwise the filament's weight; null when neither is set |
| `remaining_weight_grams` | The total minus the used weight, never below 0; null when the total is unknown |
| `location_name` | The spool's location |
| `cost` | The spool's price |
| `lot_nr` | The spool's lot number |
| `custom_note` | The spool's comment |
| `bought_at` | When the spool was registered, as an ISO 8601 UTC time |

Empty text fields are written as an empty string, as SimplyPrint's own exporter writes them; only
`total_weight_grams`, `remaining_weight_grams` and `cost` can be null. `remaining_weight_grams` is
the same figure the API shows as the spool's `remaining_weight`.

## What is left out

- **Archived spools.** Only active spools are exported.
- **Multi-colour filaments.** Only `color_hex` is written, so a filament defined by a colour list
  alone has an empty colour. The colour list and direction are not exported.
- **Extra fields and tags**, including NFC tags.
- Everything else Spoolman tracks that has no key above: temperatures, density, article
  number, printer assignment, usage history and so on.

## Alternative: upload a database backup

[SimplyPrint's help article](https://help.simplyprint.io/en/article/how-to-export-your-filament-spools-from-spoolman-import-into-simplyprint-e61m3y/)
also describes uploading a Spoolman SQLite database instead of the JSON file; follow it for the
details of what SimplyPrint reads from it. Upload a backup, not the live database file, which may
be mid-write: `POST /api/v1/backup` writes a fresh backup into the backups folder (see
[the installation guide](installation.md)) and answers with its path.

## Live sync

Keeping the two in step, for example Spoolman recording usage that SimplyPrint then sees, would
need an API on SimplyPrint's side for writing filament and usage. There is none that Spoolman NG can
use, so this is not available. Export again whenever you want a fresh copy, and expect to
reconcile duplicates in SimplyPrint yourself; `spoolman_spool_id` is there to help with that.
