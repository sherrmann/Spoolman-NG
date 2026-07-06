# Changelog

**Spoolman NG** is a community-maintained continuation of [Spoolman](https://github.com/Donkie/Spoolman) by Donkie. Full per-release notes (auto-generated from merged pull requests) are published on the [GitHub Releases](https://github.com/sherrmann/Spoolman-NG/releases) page; this file summarizes notable changes.

## Unreleased

- **Repository renamed to [`sherrmann/Spoolman-NG`](https://github.com/sherrmann/Spoolman-NG).** Old `github.com/sherrmann/Spoolman` links — including existing Moonraker `repo:` entries — keep working through GitHub's redirects. The API docs moved to <https://sherrmann.github.io/Spoolman-NG/> with **no** redirect from the old address.
- **Docker images renamed** to `ghcr.io/sherrmann/spoolman-ng` and `cookiemonster95/spoolman-ng`. The old `ghcr.io/sherrmann/spoolman` / `cookiemonster95/spoolman` images stay pullable but are frozen at the last tag published before the rename — update the `image:` line in your compose file; data volumes and settings are unaffected.

## [2026.6.0] — 2026-06-30

First release of the Spoolman NG fork, built on upstream Spoolman 0.23.1.

- **NFC spool identification** — TigerTag, OpenPrintTag, and QIDI tags. Included in the Docker images for all architectures (`amd64`, `arm64`, `armv7`).
- **Filament label printing** with separate presets, QR codes, and filament QR scanning support.
- **Redesigned home dashboard** with KPI cards and inventory analytics.
- Merged upstream community PRs: extra-field filter/sort, 3D Filament Profiles import, weight-delta events, and calibration.
- **Fork infrastructure**: multi-arch images published to GHCR (`ghcr.io/sherrmann/spoolman`) and Docker Hub (`cookiemonster95/spoolman`); CalVer releases with `:latest`, `:edge`, and `:sha-*` tags; and one-click updates via Moonraker's `update_manager`.

[2026.6.0]: https://github.com/sherrmann/Spoolman-NG/releases/tag/v2026.6.0
