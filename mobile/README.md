# Spoolman Companion (mobile app)

The Android/iOS companion app for Spoolman NG: a thin React Native (Expo)
shell that shows your server's full web UI in a WebView and adds the two
things a browser cannot deliver on the default plain-HTTP LAN deployment —
**native camera scanning** and **native NFC**. Design, rationale and roadmap:
[docs/mobile-companion-app.md](../docs/mobile-companion-app.md).

**Milestone: P0 (Android-first proof of concept).** What works:

- Connect to any Spoolman NG server (`http://pi:7912`, sub-path deploys,
  HTTPS behind a proxy). The server is probed via `/api/v1/info` and
  `/api/v1/auth/status`; an optional API token is stored in the platform
  keystore and seeded into the web UI's `localStorage` seam. A login performed
  inside the web UI is mirrored back and persisted.
- Full web UI in the WebView (hardware back navigates history; external links
  open in the system browser).
- **QR/barcode scan button**: decodes the printed label payloads
  (`WEB+SPOOLMAN:S-<id>` and deep-link URLs, spool/filament/location) with the
  web client's own grammar — `client/src/utils/scan.ts` is imported directly —
  and jumps to the matching page.
- **NFC scan button**: reads NDEF records (TigerTag external records,
  `web+spoolman:` text/URIs, deep links) locally, and dumps raw NTAG213 user
  memory (pages 4–39) for everything else, then asks the server via
  `POST /api/v1/nfc/lookup` — the same endpoint Klipper NFC daemons use. Bound
  spools open directly; unbound tags offer server-side auto-create.

Not in P0 (next milestones, per the design doc): ISO 15693/OpenPrintTag and
MIFARE Classic/Qidi raw reads, retail-barcode lookup, native login form,
multiple server profiles, tag writing/binding, the in-page native bridge.

## Development

```bash
cd mobile
npm install
npm run typecheck   # tsc --noEmit
npm test            # vitest — pure logic only (scan grammar, NDEF, injection)
```

The pure modules in `src/lib/` are unit-tested; the native layer (camera,
NFC, WebView) is exercised on a device.

## Running on a device (Android)

NFC needs real hardware, so use a physical phone with USB debugging enabled.
Requires Android Studio (SDK + platform tools) and JDK 17+.

```bash
npm run android     # expo run:android — generates android/, builds, installs
```

The generated `android/` and `ios/` directories are build artifacts
(`npx expo prebuild` recreates them) and stay untracked.

To build an installable release APK:

```bash
npx expo prebuild --platform android
cd android && ./gradlew assembleRelease
# → android/app/build/outputs/apk/release/app-release.apk
```

## Prebuilt APKs

CI builds the APK too (`.github/workflows/mobile-apk.yml`):

- **Every release**: `spoolman-companion-<tag>.apk` is attached to the GitHub
  release (built by the `build-apk` job in `ci.yml`; a failed app build never
  blocks a server release). Trackable with
  [Obtainium](https://github.com/ImranR98/Obtainium).
- **On demand**: run the "Mobile APK" workflow from the Actions tab and grab
  the `companion-apk` artifact from the run.

Signing: by default the APK carries the standard debug signature — stable
across builds (updates install cleanly) but publicly known, which is fine only
for a sideloaded proof of concept. Set the `ANDROID_DEBUG_KEYSTORE_B64`
repository secret to switch to a private key; the keytool recipe is in the
workflow header. Installed copies must be uninstalled once after the
signature changes.

## iOS status

The Expo config already carries the iOS pieces (ATS exception for plain-HTTP
servers, NFC usage description and entitlement via the config plugins), but
iOS is untested in P0 and needs a paid Apple Developer account for the Core
NFC entitlement. Note the platform limits documented in the design doc: no
MIFARE Classic (Qidi) on iPhone, ever, and NFC reads are foreground-only.

## How it talks to the server

| Concern | Mechanism |
|---|---|
| Server detection | `GET /api/v1/info`, `GET /api/v1/auth/status` (public even with auth on) |
| Auth | Bearer token seeded into `localStorage["spoolmanApiToken"]` (the web client attaches it to axios/fetch/WS itself) |
| NFC lookup | `POST /api/v1/nfc/lookup` with `raw_data_b64` + `nfc_tag_uid`, `auto_create` on request |
| Scan payloads | `client/src/utils/scan.ts`, imported via Metro `watchFolders` (see `metro.config.js`) |
