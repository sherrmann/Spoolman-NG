# Installation & Configuration

This is the fork-maintained installation guide for **Spoolman NG**. It covers the
Docker and native installs, every supported environment variable, database
options, backups, and Moonraker-managed updates.

> Migrating from original Spoolman (Donkie/Spoolman ≤ 0.23.1)? Spoolman NG is a
> drop-in replacement: point it at your existing database (or data directory)
> and it will migrate the schema automatically on startup. **Back up your
> database first.**

## Docker (recommended; the only supported option on Windows/macOS)

```yaml
services:
  spoolman:
    image: ghcr.io/sherrmann/spoolman-ng:latest # or cookiemonster95/spoolman-ng:latest on Docker Hub
    restart: unless-stopped
    volumes:
      # Mount the host directory "./data" into the container, keeping your
      # database outside the container lifecycle:
      - ./data:/home/app/.local/share/spoolman
    ports:
      - "7912:8000"
    environment:
      - TZ=Europe/Stockholm # timezone, used for timestamps in the UI/API
      # - PUID=1000         # user id that owns the data volume
      # - PGID=1000         # group id that owns the data volume
```

Start it with `docker compose up -d` and open `http://localhost:7912`.

Image tags: `:latest` (newest release), `:YYYY.M.PATCH` (pinned release,
e.g. `:2026.6.1`), `:edge` (latest master build), `:sha-<commit>`. Architectures:
`amd64`, `arm64`, `armv7` — all with NFC support included.

### Rootless Podman (Fedora / SELinux)

Under **rootless Podman**, the bind-mounted data directory is remapped through
Podman's user namespace, so it is not owned by the container's UID 1000 — and on
SELinux systems (Fedora, RHEL) the container is additionally denied access unless
the volume is relabelled. Spoolman then crash-loops with *"Data directory is not
writable"* / *"cannot read directory … Permission denied"*. This is fixed
host-side, not in the image:

- **SELinux relabel** — add `:Z` (private) to the bind mount so Podman relabels
  it for the container: `- ./data:/home/app/.local/share/spoolman:Z`.
- **User-namespace mapping** — run with `--userns=keep-id` (maps the container's
  UID 1000 to your host user), **or** set `PUID`/`PGID` to the host owner of
  `./data`, **or** `chown` the directory to the namespaced UID.

With `podman-compose`, keep the `:Z` suffix on the `volumes:` entry and add
`userns_mode: keep-id` to the service.

## Native install (Linux)

One line fetches the latest release and runs the installer (sets up
[uv](https://docs.astral.sh/uv/), the Python environment, and an optional
systemd service):

```bash
curl -fsSL https://github.com/sherrmann/Spoolman-NG/releases/latest/download/spoolman.zip -o spoolman.zip \
  && unzip spoolman.zip -d ~/Spoolman && cd ~/Spoolman && bash ./scripts/install.sh
```

The installer creates `.env` from `.env.example`, which sets the port to
**7912** — the UI then runs on `http://<host>:7912`. All configuration lives in
that `.env` file (see the reference below). The database is stored in a
separate data directory, so updates never touch it.

The native install omits the optional **NFC** (USB reader) feature by default;
add it with `uv sync --extra nfc`. For reader hardware, USB pass-through, udev
rules, the `SPOOLMAN_NFC_*` variables, and the browser Web NFC (HTTPS/Android)
requirements, see the [NFC guide](nfc.md).

### One-click updates from Moonraker (Klipper users)

Two steps. First allow Moonraker to restart the service by adding `Spoolman` on
its own line at the bottom of `~/printer_data/moonraker.asvc`. Then add this to
`moonraker.conf` (adjust `path` to your install directory):

```ini
[update_manager Spoolman]
type: zip
channel: stable
repo: sherrmann/Spoolman-NG
path: ~/Spoolman
virtualenv: .venv
requirements: requirements.txt
persistent_files:
  .env
  uv
managed_services: Spoolman
```

Spoolman NG then appears in Mainsail/Fluidd's update list. On each update
Moonraker downloads the new release zip, extracts it over the install,
reinstalls changed Python dependencies into `.venv`, and restarts the
`Spoolman` service. Notes:

- The section name is capital-S **Spoolman**, matching the systemd unit the
  installer creates and the `moonraker.asvc` entry.
- `.venv` is preserved automatically (Moonraker keeps a `virtualenv` that lives
  inside `path`); `.env` and the installer's local `uv/` toolchain need the
  explicit `persistent_files` entries. Everything else is replaced on update.
- Do **not** use `type: web` — Moonraker's web updater is for static front-ends
  (Mainsail/Fluidd themselves): it deletes everything not in `persistent_files`
  (including `.venv`), never reinstalls dependencies, and never restarts the
  service.
- The recipe needs a release that ships `requirements.txt` at the zip root
  (releases after 2026-07-19). Moonraker checks the file exists at startup, so
  on an older install re-run the install one-liner once (with `unzip -o`)
  before adding the stanza.

**Migrating an existing native install** (set up before 2026-07-19): older
releases shipped a `release_info.json` whose project name does not match the
GitHub repository, and Moonraker trusts that file over your configured `repo:`
— update checks fail until it is corrected. Fix it once, then restart Moonraker:

```bash
sed -i 's/"Spoolman NG"/"Spoolman-NG"/' ~/Spoolman/release_info.json
sudo systemctl restart moonraker
```

(Re-downloading the latest zip over the install fixes it too.)

## Connecting your printers (Moonraker clients)

Install the Spoolman **server once**. Each printer is a **client** — it does
**not** need its own Spoolman install, only a few lines in its `moonraker.conf`
pointing at the shared server:

```ini
[spoolman]
server: http://<spoolman-host>:7912
# sync_rate: 5
```

Restart Moonraker and the printer reports filament usage to that one Spoolman
instance; repeat the stanza on every printer. Note this is **not** the same as
the `[update_manager Spoolman]` block above — that one only auto-updates the
Spoolman software from Mainsail/Fluidd, whereas `[spoolman]` is what actually
wires a printer into filament tracking. See the
[Moonraker `[spoolman]` documentation](https://moonraker.readthedocs.io/en/latest/configuration/#spoolman)
for all options.

## Environment variable reference

Every variable is optional unless noted. In Docker, set them under
`environment:`; in a native install, put them in `.env`.

### Database

| Variable | Default | Description |
|---|---|---|
| `SPOOLMAN_DB_TYPE` | `sqlite` | One of `sqlite`, `postgres`, `mysql`, `cockroachdb`. |
| `SPOOLMAN_DB_HOST` | — | Database host (non-SQLite). |
| `SPOOLMAN_DB_PORT` | — | Database port (non-SQLite). |
| `SPOOLMAN_DB_NAME` | — | Database name (non-SQLite; must NOT be set for SQLite). |
| `SPOOLMAN_DB_USERNAME` | — | Database username. |
| `SPOOLMAN_DB_PASSWORD` | — | Database password. |
| `SPOOLMAN_DB_PASSWORD_FILE` | — | Path to a file containing the password (e.g. a Docker secret); alternative to `SPOOLMAN_DB_PASSWORD`. |
| `SPOOLMAN_DB_QUERY` | — | Extra connection query parameters, e.g. `unix_socket=/path/to/mysql.sock`. |
| `SPOOLMAN_DB_SCHEMA` | — | PostgreSQL/CockroachDB only: schema (search_path) to place Spoolman's tables in on a shared database (e.g. Supabase). Created automatically if missing. Ignored, with a warning, for MySQL/SQLite. |

With SQLite (the default), the database file is `spoolman.db` inside the data
directory. Schema migrations run automatically on every startup, for all
database types.

### Server & paths

| Variable | Default | Description |
|---|---|---|
| `SPOOLMAN_HOST` | `0.0.0.0` | Interface to listen on. |
| `SPOOLMAN_PORT` | `8000` | Port to listen on. Note: the Docker image listens on 8000 (map it with `ports:`), while the native installer's generated `.env` sets 7912. |
| `SPOOLMAN_BASE_PATH` | — | Serve Spoolman under a sub-path, e.g. `/spoolman` for `myhost.com/spoolman`. The web client, PWA manifest, and service worker are all base-path aware. |
| `SPOOLMAN_DIR_DATA` | `~/.local/share/spoolman` | Data directory (SQLite DB lives here). |
| `SPOOLMAN_DIR_BACKUPS` | `<data dir>/backups` | Where SQLite backups are written. |
| `SPOOLMAN_DIR_LOGS` | `<data dir>` | Log directory. |
| `SPOOLMAN_LOGGING_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `PUID` / `PGID` | `1000` | Docker only: uid/gid of the in-container user that owns the data volume. Applied only when the container starts as root; under `--user`/`runAsNonRoot` they are ignored with a logged notice — pick the uid/gid via `--user` (or `securityContext`) instead, and make sure the data dir is writable by that uid (or point `SPOOLMAN_DIR_DATA` at one that is). |

### Features

| Variable | Default | Description |
|---|---|---|
| `SPOOLMAN_METRICS_ENABLED` | `FALSE` | Expose Prometheus metrics at `/metrics` — see [monitoring.md](monitoring.md). |
| `SPOOLMAN_AUTOMATIC_BACKUP` | `TRUE` | Nightly SQLite backup at midnight; the 5 most recent backups are kept in the backups directory. |
| `EXTERNAL_DB_URL` | `https://sherrmann.github.io/SpoolmanDB/` | Source of the community filament catalog ([SpoolmanDB](https://github.com/sherrmann/SpoolmanDB)). Set to an empty string to disable syncing. |
| `EXTERNAL_DB_SYNC_INTERVAL` | `3600` | Catalog sync interval in seconds; `0` syncs only at startup. |

### Security-relevant

| Variable | Default | Description |
|---|---|---|
| `SPOOLMAN_API_TOKEN` | — | When set, all `/api/v1` requests require `Authorization: Bearer <token>` (websockets use a `?token=` query parameter), except `GET /api/v1/health` and the OpenAPI docs. `/metrics` and the web assets are not gated. A single shared machine secret; for per-user logins use accounts (below). See [Security & exposure](../README.md#security--exposure). |
| `SPOOLMAN_AUTH_SECRET` | — | Optional signing key for user-account login tokens (below). When set (or when `SPOOLMAN_API_TOKEN` is set), logins survive restarts; otherwise a fresh key is generated per process and users log in again after a restart. Never written to disk. |
| `SPOOLMAN_DEBUG_MODE` | `FALSE` | Relaxes CORS to all origins. Never enable in production. |
| `SPOOLMAN_CORS_ORIGIN` | — | Comma-separated allowed CORS origins (or `*`). |

### Authentication & user accounts

Authentication is **opt-in**; by default there is none, exactly as before. Two
mechanisms are available and can be combined:

- **Shared machine token** — set `SPOOLMAN_API_TOKEN` (above). Best for
  integrations (Moonraker, OctoPrint) that send a fixed bearer header.
- **User accounts** — create accounts under **Settings → Users**. The first
  account is always an administrator; further users can be **administrators**
  (full access) or **read-only** (may view everything but not make changes).
  Once any account exists, the web UI requires login. Accounts are optional and
  independent of the machine token, which keeps working as a never-expiring
  key for machine clients.

Passwords are stored only as salted `scrypt` hashes. For stronger or federated
control (SSO/OIDC), place Spoolman behind a reverse proxy — see the
[Security & exposure](../README.md#security--exposure) section of the README
before exposing it beyond a trusted network.

## Backups & upgrades

- SQLite: automatic nightly backups (see `SPOOLMAN_AUTOMATIC_BACKUP` above);
  for external databases use your database's own backup tooling.
- Upgrades apply database migrations automatically on startup. Take a backup
  before upgrading so you can roll back.
- To restore a SQLite backup, stop Spoolman, replace `spoolman.db` in the data
  directory with the backup file, and start again.

### Migrating between native and Docker

Your data lives in one place regardless of install method, so switching is just
a matter of moving the data directory:

- **Native → Docker**: copy the contents of the native data directory
  (`SPOOLMAN_DIR_DATA`, default `~/.local/share/spoolman`, including
  `spoolman.db`) into the host folder you bind-mount in Docker (the `./data` in
  the compose example).
- **Docker → native**: copy the bind-mounted `./data` folder's contents into the
  native `SPOOLMAN_DIR_DATA`.

Stop Spoolman on both sides first, and copy the whole directory (database plus
`backups/`). Migrations run automatically on the next start if the schema
differs.

## Uninstalling

**Docker:** `docker compose down` (add `-v` only if the database lives in a named
volume you also want removed), then delete the bind-mounted `./data` directory
and the compose file.

**Native / systemd:** the installer can register an enabled, auto-restarting
systemd service, so removing it takes a few steps:

```bash
# Stop and disable the service, then remove its unit file
sudo systemctl disable --now Spoolman.service
sudo rm /etc/systemd/system/Spoolman.service
sudo systemctl daemon-reload

# Remove the install directory (virtual environment + code) and the data
rm -rf ~/Spoolman
rm -rf ~/.local/share/spoolman   # or your SPOOLMAN_DIR_DATA — this is your database, back it up first
```

If you used a custom `SPOOLMAN_DIR_DATA` or `SPOOLMAN_DIR_BACKUPS`, remove those
paths instead. Back up the database first if you might want it later.

## QR codes & scanning

Spoolman's label printer and in-app scanner use a small `WEB+SPOOLMAN:` URI
scheme (the scanner also reads the equivalent deep-link URLs and, since they are
just text, common 2D symbologies — QR, Data Matrix, Aztec, PDF417):

| Payload | Meaning |
|---|---|
| `WEB+SPOOLMAN:S-<id>` | A spool, by id. |
| `WEB+SPOOLMAN:F-<id>` | A filament, by id. |
| `WEB+SPOOLMAN:L-<id>` | A location, by id. |
| `WEB+SPOOLMAN:CLEAR` | **Reserved** "clear the active spool" sentinel. |

`WEB+SPOOLMAN:CLEAR` is a documented convention for third-party integrations
(e.g. a barcode scanner feeding Moonraker) to agree on one value for "unload the
active spool". Spoolman itself has no notion of an active spool — that state
belongs to consumers like Moonraker — so scanning it in the app is simply
acknowledged rather than acted on. The scanner can also read a manufacturer's
retail UPC/EAN barcode and look it up by article number.
