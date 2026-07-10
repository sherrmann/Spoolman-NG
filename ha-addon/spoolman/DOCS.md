# Spoolman NG

Run the [Spoolman NG](https://github.com/sherrmann/Spoolman-NG) server — a community-maintained
continuation of Spoolman for tracking your 3D-printer filament spool inventory — directly on Home
Assistant OS.

> ⚠️ **Experimental.** This add-on packaging (issue #89) has not been exercised against a live
> Supervisor. Please report any problems on the repository.

## Installation

1. Add this repository to the add-on store (**Settings → Add-ons → Add-on Store → ⋮ → Repositories**):
   `https://github.com/sherrmann/Spoolman-NG`
2. Install **Spoolman NG** and start it.
3. Open the web UI on port `8000` of your Home Assistant host.

## Data

The add-on stores everything — the default SQLite database, backups and cache — under its persistent
`/data` volume (`SPOOLMAN_DIR_DATA=/data`), so your inventory survives restarts and add-on updates.

## Configuration

By default the add-on uses the bundled SQLite database and needs no configuration. To use an external
database instead, set the options below (they map to Spoolman's standard `SPOOLMAN_DB_*` environment
variables):

| Option        | Description                                                        |
| ------------- | ------------------------------------------------------------------ |
| `db_type`     | `sqlite` (default), `postgres`, `mysql` or `cockroachdb`.          |
| `db_host`     | Database host. Required for the external database types.           |
| `db_port`     | Database port.                                                     |
| `db_name`     | Database name.                                                     |
| `db_username` | Database user.                                                     |
| `db_password` | Database password.                                                 |
| `api_token`   | Optional bearer token; when set, the API requires it (issue #48).  |

Example (external PostgreSQL):

```yaml
db_type: postgres
db_host: core-postgresql
db_port: 5432
db_name: spoolman
db_username: spoolman
db_password: your-password
```

## Integrating with Home Assistant

To surface your spools as Home Assistant entities, pair this add-on with the third-party
[Spoolman HACS integration](https://github.com/Disane87/spoolman-homeassistant), pointing it at
`http://<home-assistant-host>:8000`.
