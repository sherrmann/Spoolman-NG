# Changelog

**Spoolman NG** is a community-maintained continuation of [Spoolman](https://github.com/Donkie/Spoolman) by Donkie. Full per-release notes (auto-generated from merged pull requests) are published on the [GitHub Releases](https://github.com/sherrmann/Spoolman-NG/releases) page; this file summarizes notable changes.

## Unreleased

- **Fixed: Moonraker one-click updates were broken four ways** (#261–#264, found by the deployment-targets audit): `release_info.json` now names the GitHub repo exactly (`Spoolman-NG`) so Moonraker's update checks work — existing native installs need the one-time fix in the [migration note](docs/installation.md#one-click-updates-from-moonraker-klipper-users); release titles are now the bare tag so Moonraker stops showing a perpetual "update available"; the release zip ships a root `requirements.txt` and the installer seeds `pip` into `.venv`, enabling the newly documented `type: zip` updater recipe (dependency reinstalls + service restart) — the previous `type: web` recipe, which **wiped `.venv` and `.env` on first update**, is gone from the docs; and `scripts/*.sh` inside the zip are executable again, so the documented install one-liner works.
- **New: deployment-channel contract tests (Tier 1)** in `tests_deployment/` (#277) — a locally runnable harness (`tests_deployment/run.sh`) that exercises the published artifacts through their real consumers: the release-zip contract, `scripts/install.sh` on Debian/Fedora/Arch containers, **real Moonraker** validating the updater recipe via its own API, and the Home Assistant add-on options contract. Red assertions cite the issue they pin; `SPOOLMAN_ZIP_PATH` lets them verify unreleased artifacts.

## [2026.7.10] — 2026-07-11

- **Digital Asset Links: `handle_all_urls` served too** — Bitwarden (and other credential managers that validate app↔site association themselves) require the `handle_all_urls` relation in `/.well-known/assetlinks.json`; the server now serves both relations, so in-app passkey flows work with third-party credential managers as well.

## [2026.7.9] — 2026-07-11

- **Frictionless passkey setup**: the server now serves `/.well-known/assetlinks.json` itself (no manual reverse-proxy config), and the companion app gained an in-app **passkey setup assistant** that reads the app identity natively and walks through the domain association.
- **Companion app passkeys**: the login WebView supports WebAuthn ceremonies (via the WebView's `WEB_AUTHENTICATION_SUPPORT_FOR_APP` mode), so passkey login through a forward-auth portal (e.g. Authelia) works inside the app.
- **Companion app self-update (Android)**: the app checks GitHub releases and can download and install the release APK in-app.

## [2026.7.8] — 2026-07-10

- **Companion app: forward-auth gateways supported** — a server behind Authelia or a similar portal is detected during setup, and login completes through an in-WebView portal flow instead of a dead-end connection error.

## [2026.7.7] — 2026-07-10

- **Fixed: auth blocked every intended-open endpoint on real deployments.** With an API token or user accounts configured, `/api/v1/health`, `/docs`, `/redoc`, `/auth/status` and even `/auth/login` returned 401 — making password login impossible and breaking health monitoring. The middleware compared its sub-app-relative open-path list against the full request path (Starlette keeps the mount prefix in `root_path`); the unit harness drove the app unmounted, which is why tests stayed green. Found by the Home Assistant add-on live-testing round; now covered by mounted-app regression tests including `SPOOLMAN_BASE_PATH` prefixes.
- **Home Assistant add-on moved to a dedicated repository**: [`sherrmann/spoolman-ng-addons`](https://github.com/sherrmann/spoolman-ng-addons) — Supervisor requires the repository manifest at the git root, so the in-tree `ha-addon/` packaging could only ever be installed by manual copy. The add-on is now installable by URL from the HA add-on store, and every release pushes a matching version bump there so updates appear in the HA UI automatically.
- **API docs deploy fixed**: docs now deploy from master pushes — tag refs are blocked by the Pages environment.

## [2026.7.6] — 2026-07-10

- **Translations completed for every language**: the ~300 keys per locale that accumulated untranslated over the 2026.7.x feature wave (auth, printers, locations, statistics, weigh workflow, bulk edit, …) are now translated in all locales, with correct language-specific plural forms. CI now enforces **placeholder integrity** — a translation that drops a `{{variable}}` or `<tag>` fails the build (this immediately caught 34 stale/broken values, now fixed).
- **UK English added and made the default**: `en-GB` (British spellings, UK date formats) is used unless the browser or the user picks another language; the previous `en` remains available as *English (US)* — and its date pickers now consistently use US formats instead of the old US-strings/UK-formats mix.
- **Home dashboard**: the redundant page title/subtitle is gone; the "Value" KPI is now an honest **estimated stock value** (spool price falling back to filament price, scaled by remaining weight — previously it summed only explicit spool prices); the filament KPI footer shows the distinct material count instead of the meaningless "all synced".
- **Spool list**: the totals row is always visible and sums the **selected** spools when a selection exists (otherwise the shown page); *Show Archived* now shows **only** archived spools (new `archived` query filter on `GET /api/v1/spool`); the bulk bar offers Archive or Unarchive to match the active view; the filament-name link uses the normal text colour; toolbar buttons have tooltips; *Hide Columns* is now *Columns*.
- **Colour filter**: leads with a one-click palette of common filament colours (full picker behind *More colors*), and the toolbar button shows the active colour.
- **Spool page**: a summary card with swatch, tags, stock bar and key numbers; a *Sibling spools* header button that lists every spool of the same filament; adjusting filament now refreshes the usage history immediately.
- **Filament list**: aligned with the spool list — inline editing (material, price, article number, comment), a colour-tile grid view, the Columns manager with drag-to-reorder/resize, and toolbar tooltips.
- **Label printing**: the live preview warns when label content is clipped or the grid cannot fit the paper.
- **Home Assistant add-on**: fixed the base image name (`spoolman-ng`) so the add-on actually builds; `poe bump` now keeps the add-on version in step; documented the working local-add-on install path.
- **Release pipeline**: images/releases now require the unit, client and e2e suites to pass; API docs redeploy on release tags.

## [2026.7.0] – [2026.7.5] — 2026-07

Six releases; full auto-generated notes on the [GitHub Releases](https://github.com/sherrmann/Spoolman-NG/releases) page. Highlights:

- **Repository renamed to [`sherrmann/Spoolman-NG`](https://github.com/sherrmann/Spoolman-NG).** Old `github.com/sherrmann/Spoolman` links — including existing Moonraker `repo:` entries — keep working through GitHub's redirects. The API docs moved to <https://sherrmann.github.io/Spoolman-NG/> with **no** redirect from the old address.
- **Docker images renamed** to `ghcr.io/sherrmann/spoolman-ng` and `cookiemonster95/spoolman-ng`. The old `ghcr.io/sherrmann/spoolman` / `cookiemonster95/spoolman` images stay pullable but are frozen at the last tag published before the rename — update the `image:` line in your compose file; data volumes and settings are unaffected.
- **Optional user accounts** (password login, admin/read-only roles), API tokens, and an experimental Home Assistant add-on package.
- **Locations** as a first-class entity with custom fields, scannable location labels and scan-to-move; **printer** entity with spool assignment.
- **List upgrades**: free-text search, colour-similarity filter, bulk edit/archive, weigh-spools workflow, drag-to-reorder/resize columns, hue sorting, totals row, grid view, inline editing, unit auto-scaling.
- **Spool intelligence**: usage & cost statistics (`/api/v1/stats/usage`), per-spool usage-event history and weight-history chart, per-spool colour/diameter overrides, idempotent use/measure endpoints.
- **Filament & import**: slicer-profile export, sliced-`.3mf` bulk adjust, retail-barcode lookup, SpoolmanDB catalog descriptors, temperature ranges.
- The client bundle is now built inside the Dockerfile, so `docker build .` works from a clean checkout.

## [2026.6.0] — 2026-06-30

First release of the Spoolman NG fork, built on upstream Spoolman 0.23.1.

- **NFC spool identification** — TigerTag, OpenPrintTag, and QIDI tags. Included in the Docker images for all architectures (`amd64`, `arm64`, `armv7`).
- **Filament label printing** with separate presets, QR codes, and filament QR scanning support.
- **Redesigned home dashboard** with KPI cards and inventory analytics.
- Merged upstream community PRs: extra-field filter/sort, 3D Filament Profiles import, weight-delta events, and calibration.
- **Fork infrastructure**: multi-arch images published to GHCR (`ghcr.io/sherrmann/spoolman`) and Docker Hub (`cookiemonster95/spoolman`); CalVer releases with `:latest`, `:edge`, and `:sha-*` tags; and one-click updates via Moonraker's `update_manager`.

[2026.7.6]: https://github.com/sherrmann/Spoolman-NG/releases/tag/v2026.7.6
[2026.7.0]: https://github.com/sherrmann/Spoolman-NG/releases/tag/v2026.7.0
[2026.7.5]: https://github.com/sherrmann/Spoolman-NG/releases/tag/v2026.7.5
[2026.6.0]: https://github.com/sherrmann/Spoolman-NG/releases/tag/v2026.6.0
