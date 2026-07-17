# Device Testing List

A practical checklist of the devices, platforms, and hardware to test before
shipping a release or claiming a feature works. This complements
[docs/nfc.md](nfc.md) (NFC setup) and
[docs/mobile-companion-app.md](mobile-companion-app.md) (companion app
design) — this doc is the "what to physically go test" list, not a setup
guide.

**Priority tags**, borrowed from [MASTERPLAN.md](../MASTERPLAN.md):

- **P0** — untested here means a headline feature might be broken for real users. Test every release.
- **P1** — meaningfully common setup; test when touching related code.
- **P2** — best-effort/shrinking platform; spot-check periodically.
- **Gap** — no code/docs target this today. Don't assume it works; say so if asked.

CI coverage is noted per item so you know what a human still needs to verify
by hand vs. what a green pipeline already proves.

## 1. Deployment platforms

| Platform | Priority | CI coverage | What to actually check |
|---|---|---|---|
| Docker, `linux/amd64` | P0 | Full 4-database integration matrix (`test` job, `.github/workflows/ci.yml`) | Standard dev/CI target — lowest risk. |
| Docker, `linux/arm64` (Pi 3/4/5, 64-bit OS) | P0 | QEMU boot + `/api/v1/health` smoke only (`build-arm64` job) | Boot the image on **real Pi hardware**, not just QEMU: run a migration from an older SQLite DB, exercise NFC USB passthrough, confirm dashboard aggregation stays snappy at a few thousand spools. |
| Docker, `linux/arm/v7` (32-bit Pi OS) | P2 — best-effort | QEMU boot + `/api/v1/health` smoke only (`build-armv7` job) | `psycopg2`/`greenlet`/`cbor2` compile from source with an `LD_PRELOAD` workaround (see `Dockerfile`) — verify the image actually starts on real 32-bit hardware after any dependency bump, since this path is the most fragile. |
| Native Linux install (`scripts/install.sh`) | P1 | Not exercised in CI | Run the script fresh on Debian, Arch, and Fedora (the three families it detects) — check `uv` setup and the optional `systemd` user service actually starts and survives a reboot. |
| Docker Desktop on Windows | P1 | None | The *only* supported Windows path — confirm volume mounts and port publishing work as documented. |
| Docker Desktop on macOS | P1 | None | Same as Windows — only supported via Docker. |
| Rootless Podman (Fedora/SELinux) | P2 | None | Needs `:Z` relabeling and `--userns=keep-id`/`PUID`/`PGID` per `docs/installation.md` — worth a periodic manual check since SELinux denials are easy to miss silently. |
| Moonraker one-click update (`[update_manager spoolman]`) | P1 | None | Confirm `release_info.json` in a real release is picked up by Moonraker's `web` update type end-to-end. |
| Home Assistant OS/Supervisor add-on | P1 | Lives in the separate `sherrmann/spoolman-ng-addons` repo; `sync-ha-addon` job only bumps its version file | Test in that repo, not here — but flag here if a Spoolman-NG change (base path, env vars) could break the add-on wrapper. |
| Synology / Unraid / TrueNAS (Docker GUI) | Gap | None | No dedicated docs or manifests exist. Generic Docker Compose *probably* works but is genuinely untested — if you have access to one of these, this is the highest-value gap to close. |
| Kubernetes / Helm | Gap | None | No manifests exist anywhere in the repo. Don't imply support exists. |

## 2. Databases

All four are CI-tested via `tests_integration/docker-compose-{sqlite,postgres,mariadb,cockroachdb}.yml` in the `test` matrix job — P0 coverage is already good here. Still worth a manual pass when touching migrations:

- [ ] SQLite (default, zero-config)
- [ ] PostgreSQL
- [ ] MySQL/MariaDB
- [ ] CockroachDB

## 3. Browsers & PWA

| Browser | Priority | CI coverage |
|---|---|---|
| Chrome/Chromium (desktop) | P0 | Playwright e2e (`client/playwright.config.ts` — the **only** configured project is `chromium`) |
| Chrome on Android | P0 | None automated — this is the **only** browser/OS combo that supports Web NFC scanning, so manually verify the NFC scan flow here every release |
| Firefox | P1 | None automated — only referenced in the dev `browserslist` entry |
| Safari (macOS) | P1 | None automated |
| Safari on iOS | P1 | None automated; also relevant to the "Add to Home Screen" PWA install flow |
| Opera Mini | Gap | Explicitly excluded from `browserslist` (`not op_mini all`) — don't test, it's intentionally unsupported |

Also check on at least one real device per OS:
- [ ] PWA install ("Add to Home Screen") on Android Chrome and iOS Safari
- [ ] Confirm the app is **online-first by design** — `navigateFallback: null` in `vite.config.ts` means a cold offline launch is not expected to work; don't file that as a bug, but do verify the service worker doesn't crash the page when the network drops mid-session
- [ ] Sub-path deploys (`SPOOLMAN_BASE_PATH`) still resolve the manifest/icons correctly

## 4. Mobile companion app (`mobile/`)

Status: **P0 proof-of-concept, Android-first.** CI only runs typecheck + Vitest unit tests (`mobile-tests` job) — there is no emulator or device build test in CI, so this entire section is manual-only.

| Device | Priority | Notes |
|---|---|---|
| Android phone, real hardware | P0 | Primary target. Test the release APK from GitHub Releases / Obtainium, not just an Expo dev build — includes the in-app self-update flow (`REQUEST_INSTALL_PACKAGES`). |
| Android — NFC read/write | P0 | Exercise both NDEF and raw NTAG213 paths against real tags. |
| Android WebView passkey/WebAuthn | P1 | Requires the `react-native-webview` patch (`mobile/patches/`) enabling `WEB_AUTHENTICATION_SUPPORT_FOR_APP` — verify login actually works, not just that the app builds. |
| iOS, any device | Gap | **Explicitly untested in P0** per `mobile/README.md`. Needs a paid Apple Developer account for Core NFC. If you have one, this is a high-value gap to close before claiming iOS support anywhere. |
| iOS WKWebView passkeys | Gap | Called out in the repo as "a separate, untried path" — don't assume parity with Android. |

## 5. NFC hardware

Full setup guide: [docs/nfc.md](nfc.md). Hardware coverage today is thin — codec logic is unit-tested (`tests/nfc/`), but **no physical reader or tag is exercised in CI**, so this whole section is manual verification.

**Tag formats** (test all three if you have samples):
- [ ] TigerTag (NTAG213, ISO 14443A) — readable via both Web NFC and USB reader
- [ ] OpenPrintTag (Prusa's format, ISO 15693/NFC-V) — **browser-only**, no USB reader path exists for this format
- [ ] Qidi (MIFARE Classic 1K, ISO 14443A) — **USB reader only**, cannot be read via Web NFC

**USB readers** — named in code/docs as expected-to-work via `nfcpy` but explicitly flagged "not hardware-verified":
- [ ] PN532
- [ ] RC522 (also documented as a bare SPI/GPIO breakout bridged via a custom daemon — different code path from the USB readers above, worth testing separately)
- [ ] ACR122U (or other PC/SC-class reader)

For each reader tested, also confirm:
- [ ] Docker device passthrough (`devices: - /dev/bus/usb:/dev/bus/usb`) actually grants access
- [ ] Native install udev rule works for non-root reads (README gives an example VID for ACR122U: `072f`)
- [ ] Web NFC scan flow fails *with a clear reason* (not Chrome/Android, or not a secure context) rather than silently — this is a known open item in MASTERPLAN.md §4

## 6. Camera / QR & barcode scanning

`client/src/components/qrCodeScanner.tsx`, powered by `@yudiel/react-qr-scanner`. Formats: QR, Micro QR, rMQR, Data Matrix, Aztec, PDF417, EAN-13/8, UPC-A/E.

- [ ] Desktop with a single built-in/USB webcam
- [ ] Desktop/mobile with **multiple** cameras attached — confirm the camera picker (`navigator.mediaDevices.enumerateDevices()`) lets you choose the right one
- [ ] Permission-denied path (`NotAllowedError`) shows a sane error, not a blank screen
- [ ] Plain-HTTP LAN address (`InsecureContextError`) — this is the **default deployment**, so confirm the UI explains that scanning needs HTTPS rather than failing silently
- [ ] Camera already in use by another app (`NotReadableError`)
- [ ] No camera present (`NotFoundError`)

## 7. Label printing

Rendered client-side, no server hardware dependency — but still needs testing against real printers since output correctness can't be caught by unit tests alone.

- [ ] **OS print dialog path** (`react-to-print`) against at least one real printer reachable from your OS — this is the generic path Dymo/Brother/etc. go through; there's no dedicated driver code for them
- [ ] **Zebra ZPL export** (`client/src/utils/zpl.ts`) — generate a `^GFA` file and print it on an actual Zebra-class thermal printer; only byte-level output is unit-tested today, nothing confirms it renders correctly on real thermal hardware
- [ ] **Save as Image** (PNG/ZIP via `html-to-image`) — spot-check at a couple of DPI/label-size combinations

## 8. Downstream integrations (things that pull from Spoolman's API)

Spoolman-NG never dials out to these — they connect to it — but a Spoolman change can silently break them, so worth a periodic smoke test:

- [ ] **Moonraker/Klipper** `[spoolman]` component — confirm `PUT /use` still works after any API change
- [ ] **OctoPrint** via the community `octoprint-spoolman` plugin (external repo)
- [ ] **Slicer profile export** (`spoolman/slicer_profiles.py`) — generate and actually import a profile into PrusaSlicer/OrcaSlicer/Cura, not just check the file parses

Not integrated today — don't test as if they were, and correct anyone who assumes otherwise: Bambu Cloud/AMS, Prusa Connect (only Prusa's *NFC tag format* is supported, not the Connect service).

## 9. Known gaps — say so, don't guess

If someone asks "does this work on X," these are the honest answers as of this doc:

- **Synology/Unraid/TrueNAS**: no dedicated docs, no one has confirmed it — likely fine via generic Docker Compose, but unverified.
- **Kubernetes/Helm**: not supported, no manifests exist.
- **iOS (companion app)**: untested in P0; needs a paid Apple Developer account to even start.
- **Firefox/Safari**: no automated coverage, manual-only, and not verified on a regular cadence.
- **NFC reader hardware**: PN532/RC522/ACR122U are code-supported-in-theory, not hardware-verified by anyone on the project.
- **Bluetooth**: no code path exists at all.
