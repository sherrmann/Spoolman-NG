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
- **Servers behind a login portal (Authelia, Authentik, oauth2-proxy, …).**
  A forward-auth gateway blocks even the public `/api/v1/info`, so setup
  detects the wall (a 401/403 or off-origin redirect on `/info`) and, instead
  of a dead-end error, offers to continue into the app and sign in at the
  portal. The WebView shares its cookie jar with native requests
  (`sharedCookiesEnabled` / `thirdPartyCookiesEnabled`), so the portal session
  cookie set during that login also authenticates the native probe and
  `nfc/lookup` calls. A stacked Spoolman API token still rides along as a
  bearer header.
- Full web UI in the WebView (hardware back navigates history; clicked
  external links open in the system browser, while forward-auth redirects stay
  in-app to complete login).
- **QR/barcode scan button**: decodes the printed label payloads
  (`WEB+SPOOLMAN:S-<id>` and deep-link URLs, spool/filament/location) with the
  web client's own grammar — `client/src/utils/scan.ts`, vendored
  byte-identically into `src/shared/` (see below) — and jumps to the matching
  page.
- **NFC scan button**: reads NDEF records (TigerTag external records,
  `web+spoolman:` text/URIs, deep links) locally, and dumps raw NTAG213 user
  memory (pages 4–39) for everything else, then asks the server via
  `POST /api/v1/nfc/lookup` — the same endpoint Klipper NFC daemons use. Bound
  spools open directly; unbound tags offer server-side auto-create.
- **Passkeys / WebAuthn in the login WebView.** The embedded Android WebView
  has WebAuthn enabled (`WEB_AUTHENTICATION_SUPPORT_FOR_APP` via androidx.webkit),
  so `navigator.credentials` works for the login page it loads — Authelia,
  Authentik, Keycloak, or Spoolman's own login. Enabled through a
  `patch-package` patch to `react-native-webview` (see `patches/`), because the
  library does not expose the setting itself. Requires a reasonably recent
  Android System WebView; a no-op on versions without the feature. **One-time
  server setup is required** — see [Passkeys](#passkeys-webauthn) below.
- **In-app self-update (Android).** On launch the app checks the GitHub
  `releases/latest` and, when a newer `spoolman-companion-*.apk` is published,
  offers to download and install it (via the system package installer — you
  grant "install unknown apps" once). Also available on demand from the ⚙
  menu → "Check for updates". Version logic is in `src/lib/update.ts` (tested);
  the download/install is `src/update/updater.ts`. Prefer a hands-off flow?
  Point [Obtainium](https://github.com/ImranR98/Obtainium) at this repo — it
  tracks the same release asset. iOS updates go through the App Store/TestFlight.

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
| Forward-auth (Authelia, etc.) | Detected at setup when `/info` is walled off; the user signs in at the portal inside the WebView, and the shared cookie jar carries the session to native requests |
| Passkeys / WebAuthn | Enabled on the Android WebView (`WEB_AUTHENTICATION_SUPPORT_FOR_APP`) via a `patch-package` patch; needs a Digital Asset Links file on the RP domain — Spoolman serves its own, forward-auth portals need it hosted on theirs, and ⚙ → *Passkey setup* verifies it (see below) |
| Updates (Android) | `GET https://api.github.com/repos/sherrmann/Spoolman-NG/releases/latest`; newer `spoolman-companion-*.apk` is downloaded and handed to the system installer |
| NFC lookup | `POST /api/v1/nfc/lookup` with `raw_data_b64` + `nfc_tag_uid`, `auto_create` on request |
| Scan payloads | `client/src/utils/scan.ts`, vendored into `src/shared/scan.ts` by `scripts/sync-shared.mjs` (regenerated on `npm install`; `src/shared/drift.test.ts` fails when the copy is stale). Metro cannot bundle files outside the project root — Expo CLI recomputes `watchFolders` and ignores `metro.config.js` — hence the sync instead of a direct import. |

## Passkeys (WebAuthn)

Android only lets a **real browser** use passkeys for arbitrary sites without
extra setup. A normal app embedding a login page (like this one) must use
`WEB_AUTHENTICATION_SUPPORT_FOR_APP`, and Android then requires the WebAuthn
Relying Party's domain to **vouch for the app** via a
[Digital Asset Links](https://developers.google.com/digital-asset-links) file
at `https://<rp-domain>/.well-known/assetlinks.json`. Without it the passkey
ceremony fails with *"an unknown error has occurred"*. This is a platform
security rule, not a Spoolman limitation — password/OTP login works regardless.

**Which domain?** Android fetches the file from the **exact hostname** of the
WebAuthn RP ID — no parent-domain fallback, no redirects. In practice that is
the hostname in the address bar at the moment the passkey prompt appears:

- **No login portal** (Spoolman's built-in accounts, or a proxy that doesn't
  intercept): the RP is Spoolman's own domain — and **Spoolman already serves
  the file there**, so passkeys are zero-config. Self-built APKs add their
  key via the server env var `SPOOLMAN_ANDROID_CERT_FINGERPRINTS`
  (comma-separated SHA-256s, appended to the released APK's).
- **Forward-auth portal** (Authelia, Authentik, …): the RP is the **portal's
  hostname** and the file must be reachable there. Per-IdP notes below.

**In-app assistant** — ⚙ → *Passkey setup* shows the installed APK's real
package + signing fingerprint, the exact JSON to host, and checks the hosted
file with concrete pass/fail reasons. Use it instead of debugging blind.

The file Android expects (this is what Spoolman serves and the assistant
renders; the fingerprint below is the released APK's — the well-known Android
debug key, see the signing note below):

```json
[
  {
    "relation": ["delegate_permission/common.get_login_creds"],
    "target": {
      "namespace": "android_app",
      "package_name": "app.spoolman.companion",
      "sha256_cert_fingerprints": [
        "FA:C6:17:45:DC:09:03:78:6F:B9:ED:E6:2A:96:2B:39:9F:73:48:F0:BB:6F:89:9B:83:32:66:75:91:03:3B:9C"
      ]
    }
  }
]
```

If you build with your own `ANDROID_DEBUG_KEYSTORE_B64`, use *your* key's
SHA-256 — the Mobile APK workflow prints it (and a ready-to-host
`assetlinks.json`) in its run summary, or run
`apksigner verify --print-certs spoolman-companion-*.apk`. Multiple
fingerprints in one array are fine (e.g. released + self-built).

### Authelia

Authelia's RP ID is the **portal's exact hostname** (taken from
`X-Forwarded-Host`; not configurable — e.g. `auth.example.com`), so the file
must be served on that domain. Authelia itself won't serve static files; the
easiest robust option is a reverse-proxy rule on the portal domain that
forwards the path to Spoolman's built-in endpoint, so the served fingerprints
stay managed by `SPOOLMAN_ANDROID_CERT_FINGERPRINTS`:

```yaml
# Traefik (Docker labels on the Spoolman container)
- traefik.http.routers.spoolman-dal.rule=Host(`auth.example.com`) && Path(`/.well-known/assetlinks.json`)
- traefik.http.routers.spoolman-dal.service=spoolman
# No auth middleware on this router — the file must be public.
```

```caddyfile
# Caddy
auth.example.com {
  handle /.well-known/assetlinks.json {
    reverse_proxy spoolman:8000
  }
  # ... existing Authelia portal config ...
}
```

```nginx
# nginx
location = /.well-known/assetlinks.json {
  proxy_pass http://spoolman:8000;
}
```

(Serving a static copy of the JSON works just as well.) Passkey login in the
portal itself needs **Authelia ≥ 4.39**. If Spoolman's *own* domain is also
behind Authelia and you rely on the built-in endpoint for a different RP,
bypass it in the ACL:

```yaml
access_control:
  rules:
    - domain: spoolman.example.com
      resources: ['^/\.well-known/assetlinks\.json$']
      policy: bypass
```

### Authentik / Keycloak

Same rule: the RP ID is the hostname you see during login (the Authentik host
/ the Keycloak realm's public hostname). Host the file there — a static file
in the ingress/proxy for that domain, or a proxy rule to Spoolman's endpoint
as above.

### oauth2-proxy

oauth2-proxy doesn't run WebAuthn itself — the passkey prompt happens at the
**upstream IdP** it redirects to (Keycloak, Google, …). Self-hosted upstream:
host the file on *that* IdP's domain. Public IdPs (Google etc.) can't vouch
for your APK, so portal passkeys aren't achievable there.

### Notes

- Must be served over **HTTPS** with `Content-Type: application/json`, **no
  redirects**, and a **publicly-trusted certificate** — Google's verifier
  won't accept self-signed/private-CA certs even if the device trusts them.
- Behind a forward-auth proxy, the path must be reachable unauthenticated.
- Needs a recent Android System WebView and a device passkey provider (e.g.
  Google Password Manager). `mediation: "conditional"` (autofill) is not
  supported in a WebView; the user taps the passkey button.
- Verification results are cached by the platform — after fixing the file,
  give it a little time and retry.
- iOS WKWebView passkeys are a separate, untried path (associated domains).
