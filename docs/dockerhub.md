# Spoolman NG

**A community-maintained continuation of [Spoolman](https://github.com/Donkie/Spoolman)** — keep track of your inventory of 3D-printer filament spools. Drop-in compatible with the upstream image and the whole ecosystem (Moonraker/Klipper, OctoPrint, Home Assistant), plus NFC spool identification, QR label printing, user accounts, and more.

📦 **Source, docs & issues:** <https://github.com/sherrmann/Spoolman-NG>

## Quick start

```yaml
services:
  spoolman:
    image: cookiemonster95/spoolman-ng:latest   # also: ghcr.io/sherrmann/spoolman-ng
    restart: unless-stopped
    volumes:
      - ./data:/home/app/.local/share/spoolman
    ports:
      - "7912:8000"
```

Then open `http://localhost:7912`.

## Tags

| Tag | Meaning |
|---|---|
| `latest` | Newest release |
| `YYYY.M.PATCH` | A pinned release (e.g. `2026.7.12`) |
| `edge` | Latest `master` build |
| `sha-<commit>` | A specific commit |

Architectures: `amd64`, `arm64`, `armv7` — all with NFC support.

**Following an upstream Spoolman guide?** Wherever it says `ghcr.io/donkie/spoolman` or `donkieyo/spoolman`, use this image instead — ports, volume path, and environment variables are unchanged.

Full configuration reference (databases, base path, auth, backups): [Installation & Configuration guide](https://github.com/sherrmann/Spoolman-NG/blob/master/docs/installation.md). A Helm chart is published as `oci://ghcr.io/sherrmann/charts/spoolman-ng`.
