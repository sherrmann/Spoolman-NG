# Mobile Companion App — Feasibility & Design

> **Status: P0 implemented.** The Android-first proof of concept from the
> roadmap below lives in [`mobile/`](../mobile/README.md): WebView shell +
> token seeding, native camera scan → shared grammar → navigate, and NFC
> (NDEF + raw NTAG213) → `/nfc/lookup` → navigate. Later phases (P1–P3) are
> still design. This document records the feasibility assessment, the
> recommended architecture, the pitfalls (there are real ones, especially on
> iOS), and the phased roadmap.

## Why an app at all

Spoolman NG already generates QR labels, parses scans, and reads/writes NFC
tags — but the in-browser capture story is architecturally capped, and no amount
of polish inside the web client can lift the cap:

- **Camera QR scanning and Web NFC both require a secure context (HTTPS).**
  The default deployment is plain HTTP on a LAN (`http://pi:7912`, no built-in
  TLS — see [nfc.md](nfc.md#browser-scanning-web-nfc--requirements)). For the
  most common install, the floating scan button is dead on arrival unless the
  user first sets up a TLS reverse proxy. [MASTERPLAN.md](../MASTERPLAN.md)
  already concedes this: the NFC feature "quietly doesn't apply to the most
  common deployment".
- **iOS has no Web NFC, period.** WebKit (mandatory for every iOS browser)
  does not implement it. No TLS setup, no PWA work, nothing web-side ever gives
  an iPhone user NFC.
- **Web NFC is NDEF-only.** Even on Android/Chrome/HTTPS it cannot read Qidi
  tags (MIFARE Classic) or do raw NTAG213 page I/O — which is why the browser
  write path has to NDEF-wrap the TigerTag binary and warns that the result is
  not TigerTag-app-compatible.

A native companion app removes exactly these three constraints and nothing
else: native camera scanning works over any transport, native NFC works on both
platforms (with honest iOS caveats below), and native NFC can do raw page
reads/writes — which is *better* than what the browser can ever offer, because a
phone-written NTAG213 becomes readable by the official TigerTag app.

The server is already shaped for this. `POST /api/v1/nfc/lookup`
(`spoolman/api/v1/nfc.py`) was built for "an external device read raw tag
memory, tell me the spool": base64 raw dump in, auto-detection of
TigerTag/OpenPrintTag/Qidi, optional `auto_create`, `nfc_tag_uid` binding. The
phone is just another external reader, exactly like the Klipper NFC daemons the
endpoint was designed for. `/nfc/bind`, `/nfc/create-from-tag` and
`/nfc/encode` complete the loop. **The first app version needs zero server
changes.**

## What the app is (and is not)

The app is a **thin native shell around the hosted web UI**:

- The full product UI stays the server's React SPA, loaded in a WebView from
  the user's own server (any supported deployment, including
  `SPOOLMAN_BASE_PATH` subpaths). There is no second UI to keep in sync.
- The shell adds a native layer for the two things a browser cannot deliver on
  the default deployment: **camera scanning** and **NFC**, plus the plumbing
  they need (server profiles, token storage, onboarding).
- It is explicitly **not** a native rewrite of the UI, and not an offline
  client — Spoolman NG is an online-first inventory app and stays that way.

## Architecture options compared

| | React Native + Expo (recommended) | Capacitor | Flutter | 2× fully native | No app: document TLS + PWA |
|---|---|---|---|---|---|
| Language fit (TS/React project) | Excellent — can import `client/src/utils/scan.ts` and `tigertagCodec.ts` unchanged | Good (TS) | Poor (Dart, second toolchain) | Poor (Kotlin + Swift) | n/a |
| Remote, per-user server URL as the main surface | First-class: `react-native-webview` is a component pointed at any runtime URL, with an injection/message bridge | Poor fit: Capacitor assumes *bundled* web assets in its own webview; `server.url` is a dev-live-reload knob, not a per-user runtime setting | OK (`webview_flutter`) | OK | The PWA *is* the UI |
| NFC | `react-native-nfc-manager`: mature, free; NDEF + raw NfcA + NfcV + MIFARE Classic (Android); NDEF + ISO 15693 + NTAG commands (iOS) | The maintained plugin (`@capawesome-team/capacitor-nfc`) is sponsorware; free options are stale | `nfc_manager`: fine | Full control | **iOS: impossible, ever** |
| QR/barcode | `expo-camera` (MLKit / AVFoundation): qr, data-matrix, aztec, pdf417, ean-13/8, upc-a/e | Good plugins | `mobile_scanner`: fine | Full control | Requires TLS setup |
| Solo-maintainer burden | One codebase, three native deps | One codebase, plugin-license risk | Two ecosystems | Two full apps | Zero, but solves nothing |

**Recommendation: React Native + Expo (prebuild / dev-client workflow), one TS
codebase for both platforms.** Not Expo Go — the NFC native module requires a
custom dev client / prebuild. Exactly three native capabilities:

1. `react-native-webview` — hosts the remote Spoolman UI.
2. `expo-camera` — barcode/QR scanning. (Known gap: MLKit does not decode
   micro-QR/rM-QR, which the web scanner's zxing-wasm does. Spoolman's own
   printed labels are standard QR, so this is negligible — but document it.)
3. `react-native-nfc-manager` — NDEF, raw NfcA (NTAG213 pages), NfcV/ISO 15693
   (OpenPrintTag), MIFARE Classic (Qidi, Android only).

Why not the alternatives:

- **Capacitor**, despite being "the web-app wrapper": the wrapped content here
  is *remote and per-user*, not bundled — off Capacitor's paved path — and the
  one well-maintained NFC plugin is sponsorware, a bad dependency for an OSS
  project.
- **Flutter**: capable, but Dart discards the project's biggest asset — the
  existing, unit-tested pure-TS modules. `scan.ts` has zero DOM dependencies
  and `tigertagCodec.ts` is ArrayBuffer/DataView code that runs unchanged in
  Hermes; reimplementing them in Dart creates a drift surface.
- **Two native apps**: best platform fidelity, double the maintenance. Not
  realistic for one person.
- **"Just document TLS + PWA"**: already the status quo (`docs/nfc.md` has the
  reverse-proxy recipes) and exactly the "cumbersome" state being complained
  about. It structurally cannot fix iOS NFC or raw-tag I/O. Keep the TLS docs
  as complementary, not as the answer.

## Integration design, in layers

### v0 — zero server/client changes

Works against any current Spoolman NG release (and degrades against upstream
Spoolman, which lacks the NFC API entirely — see pitfall 7).

**Server profiles & onboarding.** A profile is
`{ name, baseUrl, token?, probed }` where `baseUrl` includes any base path
(`http://nas:7912`, `https://x.example.com/spoolman`). On add, probe two
endpoints that are public even when auth is enabled:

- `GET <base>/api/v1/info` → is this a Spoolman server, which version
  (feature detection).
- `GET <base>/api/v1/auth/status` → `{auth_required, accounts_enabled}` →
  show a native username/password login (`POST /api/v1/auth/login`) or a raw
  token field (`SPOOLMAN_API_TOKEN` case). Tokens go in the platform keystore
  (Keychain / Android Keystore via `expo-secure-store`), never plain storage.

**Auth injection into the WebView.** The web client reads its token from
`localStorage["spoolmanApiToken"]` (`client/src/utils/apiToken.ts`) and
attaches it to axios, `fetch` and the WebSocket (`?token=`) by itself — so the
shell only seeds that one key via `injectedJavaScriptBeforeContentLoaded`. If
the user instead logs in *inside* the WebView, a small injected snippet mirrors
the key back to the shell. This key thereby becomes a public contract (pitfall
6).

**Cleartext HTTP** (the whole point): Android network security config with
cleartext permitted (user-entered hosts are arbitrary, so no allowlist is
possible); iOS ATS exception (`NSAllowsArbitraryLoads`) with the standard
self-hosted-companion justification — the pattern Home Assistant and every
OctoPrint/Jellyfin client ships with. `NSAllowsLocalNetworking` alone is not
enough because users enter DNS names and VPN IPs that don't qualify as "local".

**Native scan button** (an overlaid native view, not inside the WebView):

- Camera scan → raw string → the **shared** `parseScanResult` /
  `isClearScan` / `looksLikeRetailBarcode` from `client/src/utils/scan.ts`.
  The URL regexes already tolerate any host and base path, so codes printed as
  deep links parse regardless of which profile scans them.
- Recognized target → navigate the WebView to `<basePath>/spool/show/<id>`
  (v0 uses a plain `location.assign` — a full SPA reload, but 100% reliable
  with zero client changes).
- Retail barcode (8/12/13/14 digits) → replicate the existing web flow
  natively: `GET /api/v1/filament?article_number="<code>"` → hit: navigate to
  spool-create prefilled with the filament; miss: offer filament-create with
  the article number. Both routes are already URL-param-driven.
- `WEB+SPOOLMAN:CLEAR` → informational toast, matching
  `client/src/components/qrCodeScanner.tsx`.

**Native NFC read**:

1. Try NDEF first, fully locally: TigerTag's external record, or URI/text
   records matching the `scan.ts` grammar → navigate directly, no server
   round-trip.
2. Otherwise dump raw memory by tech type and delegate to the server, exactly
   like a Klipper daemon: NTAG213 pages 4–39 (mirrors
   `spoolman/nfc_service.py`), ISO 15693 blocks from 0 (server detects the
   format), MIFARE Classic sector 1 / block 4 with the documented Qidi keys
   (`spoolman/qidi_codec.py`) on capable Android devices. Then
   `POST /api/v1/nfc/lookup { raw_data_b64, nfc_tag_uid }` → `spool_id` →
   navigate. No match → offer "create spool from this tag?" → re-POST with
   `auto_create: true` (the endpoint's idempotent auto-create machinery does
   the rest).
3. iOS runs the same logic inside a foreground `NFCTagReaderSession` (system
   scan sheet); the MIFARE Classic branch simply does not exist there
   (pitfall 1).

### v1 — a small client bridge (still no server changes)

Goal: the *existing web UI flows* — the unified scan modal, NFC scan/bind/write
modals — use the phone's hardware, instead of the shell bolting parallel flows
on top.

The shell injects, before page load:

```js
window.SpoolmanNative = {
  v: 1, platform: "android" | "ios", appVersion: "…",
  capabilities: { qr: true, nfc: bool, nfcRawWrite: bool, nfcV: bool, mifareClassic: bool }
};
```

and the two sides speak a small versioned JSON protocol with correlation ids
(web → native via `window.ReactNativeWebView.postMessage`, native → web via an
injected `CustomEvent`): `scan.start/result`, `nfc.read`, `nfc.write`
(payload kinds `ntag_raw` / `ndef` / `qidi_block`), `nfc.cancel`,
`auth.token`, and a shared `error` shape
(`cancelled | unsupported | timeout | nfc_off | …`).

Client files touched (all small, all behind `"SpoolmanNative" in window`):

- **new** `client/src/utils/nativeBridge.ts` — detection, typed
  request/response with timeouts, capability getters; pure TS, unit-testable
  like `scan.ts`.
- `client/src/utils/apiToken.ts` — notify the bridge on set/clear (replaces
  the v0 localStorage-mirroring hack).
- `client/src/components/qrCodeScanner.tsx` — factor the scan-result pipeline
  (clear sentinel / `parseScanResult` / retail lookup / move-spool decision)
  into a function taking a raw string, so a native scan feeds the identical
  pipeline and the two-scan "move spool" flow works with native scans for
  free.
- `client/src/components/scanModal.tsx` — render a native-scan panel instead
  of the camera `<Scanner>` when native; enable the NFC segment from
  `capabilities.nfc` in addition to the existing server/browser availability.
- `client/src/utils/nfc.ts` + `client/src/components/nfcScannerModal.tsx`,
  `nfcBindModal.tsx`, `nfcWriteModal.tsx` — a third reader mode "Phone"
  alongside server/browser: read → local NDEF parse else `/nfc/lookup`; bind
  via the existing `/nfc/bind` mutation; write via `/nfc/encode` payloads (or
  the client-side TigerTag codec) written by the phone. The headline: the
  phone writes **raw NTAG213 pages**, so the result is TigerTag-app-compatible
  — something the Web NFC path can never produce.
- `client/public/locales/en/common.json` — new strings (other locales fall
  back).

Bridge contract tests live on both sides in the spirit of
`TESTING_STRATEGY.md`'s encoder/decoder-oracle approach, plus one test pinning
the `spoolmanApiToken` localStorage key as public API.

### v2 — niceties

- **Pairing QR** in the web settings page: a `spoolman+pair://` payload with
  server URL, name and (after an explicit warning tap) the token — scan it in
  the app for instant onboarding. Client-only change.
- **OS handlers** for `web+spoolman:` (Android intent filter + iOS URL type),
  so any external scanner app opens Spoolman codes in the app. Note the
  payload carries no server identity — it targets the active profile.
- **Android tap-to-open**: foreground dispatch (and an NDEF intent filter for
  cold starts) reads tags without pressing anything. iOS structurally cannot
  do this for self-hosted servers (background NFC requires universal links on
  a fixed registered domain), so iOS stays button-initiated.
- **Quick-actions screen** (native, tiny): after a scan, "use 10 g / 50 g /
  custom" via `PUT /api/v1/spool/{id}/use` with the `Idempotency-Key` header —
  already supported server-side, so flaky-LAN retries are safe by design.
- **Optional mDNS discovery** — the only server change in this entire plan,
  and low priority: opt-in `SPOOLMAN_MDNS_ENABLED` advertising
  `_spoolman._tcp` with a `path=<base_path>` TXT record. Honest caveat: useless
  behind default Docker bridge networking (works with host networking, native
  installs, and the HA add-on).

## Repo & infrastructure

- **The app lives in `mobile/` in this repository.** The bridge protocol and
  the `spoolmanApiToken` contract must move in lockstep with `client/`; a
  separate repo would orphan them.
- **Code sharing without a workspace conversion:** `scan.ts`, `scanMove.ts`
  and `tigertagCodec.ts` are dependency-free pure TS. Direct imports across
  the package boundary do **not** survive release builds — Metro only bundles
  files inside the project root, and Expo CLI (SDK 57) recomputes
  `watchFolders` itself, ignoring `metro.config.js` — so `mobile/` vendors the
  files via `scripts/sync-shared.mjs` (regenerated on `npm install`) with a
  drift test asserting the copies stay byte-identical to their sources.
  Promote to a real shared package only if a third consumer ever appears.
- **CI:** Android release APKs via `expo prebuild` + Gradle on the existing
  GitHub Actions setup, attached to GitHub Releases; PR CI runs typecheck +
  unit tests only (native builds are slow, run on release tags). iOS builds on
  a macOS runner with fastlane → TestFlight.
- **Distribution:** Android via GitHub Releases + Obtainium from day one,
  IzzyOnDroid soon after, Play Store when ready ($25 once; new personal
  accounts face the 12-testers/14-days closed-testing rule — create the
  account early, ship via GitHub meanwhile). iOS via TestFlight first, then
  the App Store ($99/yr, also a hard prerequisite for the Core NFC
  entitlement).
- **Versioning:** the app is feature-detected against the server
  (`GET /api/v1/info` + graceful endpoint probing), never lockstep. Users
  *will* point it at old or upstream Spoolman servers; the app must degrade to
  QR + local NDEF parsing with a clear "server doesn't support X" message.

## Pitfalls (the honest list)

1. **iOS cannot read MIFARE Classic — Qidi tags will never work on iPhone.**
   Core NFC has no Crypto-1 support and never has. Capability-gate it, say so
   in the docs to preempt bug reports, and keep the server USB reader as the
   Qidi path. No workaround exists.
2. **iOS NFC is foreground-only**, behind a ~60 s system sheet, and requires
   the paid developer account for the entitlement. No ambient tap-to-open:
   background NDEF reading needs universal links on a fixed registered domain
   — structurally impossible for arbitrary self-hosted servers. Design flows
   around explicit scan buttons (matches the web UX anyway); Android gets the
   ambient-tap upgrade.
3. **Android MIFARE Classic is device-dependent** (NXP NFC controller
   required; many Pixels/Samsungs yes, others no). Runtime-probe and report
   honestly in the capability object.
4. **Cleartext HTTP + the iOS local-network prompt.** Both platforms need
   explicit cleartext opt-ins (standard for this app class, but reviewable),
   and iOS 14+ shows a local-network permission prompt whose denial fails
   *silently* — onboarding must detect "request failed + private-range host"
   and point at Settings → Privacy → Local Network.
5. **Apple review guideline 4.2** ("minimum functionality" web-wrapper
   rejections) is a real risk if the app ships as *just* a WebView. Ship iOS
   only once native value is visible in the first session (server manager,
   scanner, NFC sheet); cite the app-class precedent (Home Assistant,
   OctoPrint clients, Jellyfin) in review notes.
6. **Auth fragility:** the `spoolmanApiToken` localStorage key is currently an
   internal detail; the shell depends on it, so pin it with a contract test in
   `client/` and replace injection-scraping with the explicit `auth.token`
   bridge message in v1. Login tokens expire after 7 days — detect the
   in-WebView 401/login and re-sync.
7. **Version skew and upstream servers.** Feature-detect, never assume: on
   upstream Spoolman there is no `/nfc/*`, no `/auth/*`. Degrade to QR +
   local NDEF with a clear message ("needs Spoolman NG ≥ X").
8. **WebSocket auth** uses `?token=` and works unchanged inside the WebView.
   Only if the native layer later opens its own WS does it need the same
   convention. (Tokens in URLs appear in reverse-proxy logs — already true for
   the web app today, not new exposure.)
9. **Multi-server storage isolation.** localStorage is per-origin (two servers
   on different origins are naturally isolated); two instances on the *same*
   origin under different base paths share the token key — rare, document it.
   WebView cookie/data stores are per-app. Spoolman's *own* auth is
   header/localStorage-based, but a **forward-auth gateway in front of it
   (Authelia, Authentik, oauth2-proxy, Traefik/Caddy ForwardAuth) is
   cookie-based** — so the WebView shares its cookie jar with native fetch
   (`sharedCookiesEnabled` / `thirdPartyCookiesEnabled`) and setup detects the
   wall (401/403 or off-origin redirect on the public `/info`) to route the
   user through an in-WebView portal login. See `src/lib/forwardAuth.ts`. The
   gateway cookie and the Spoolman bearer token are independent layers and
   both travel with each request once present. Open follow-ups: portal
   sessions expire (a lapsed cookie surfaces as a 401 on native lookups →
   re-open the UI to re-login); iOS WKWebView cookie sharing needs on-device
   confirmation.
10. **No service worker in the WebView over HTTP** — harmless: registration
    already no-ops on insecure origins today, and the app is online-first.
    Suppress PWA install prompts when `SpoolmanNative` is present.
11. **Camera permission UX**: purpose strings on both platforms, request on
    first scan tap (not at startup), graceful denied-state with a settings
    deep link.
12. **Raw NTAG writes on iOS are fiddly** (session timeouts, tag tearing if
    the user pulls away). Write-then-verify (read back pages 4–39 and
    compare), "hold still" UI, server-reader write as fallback. NDEF-wrapped
    TigerTag payloads need NTAG215+ — 144 bytes plus NDEF overhead does not
    fit NTAG213's 144-byte user memory; enforce with a capacity check,
    mirroring the existing web warning.
13. **ISO 15693 quirks** (block-size variance, per-chip `readMultipleBlocks`
    limits, multi-second reads). Read the capability container first, chunk
    with progress UI — and **never port the CBOR codec**: POST the raw dump to
    `/nfc/lookup` and let the tested server decoder do the work.
    (OpenPrintTag *write* support doesn't exist server-side either; out of
    scope.)
14. **The chronic cost:** store upkeep is a permanent ~1–2 days/quarter tax —
    annual RN/Expo bumps, yearly Play target-API bumps, Apple fees and review
    churn. Mitigations: the deliberately tiny native surface (three libs),
    Expo prebuild (no hand-maintained native projects), GitHub
    Releases/Obtainium as the Android pressure valve, and iOS explicitly
    allowed to trail Android.
15. **WebView gaps to sand down:** Android hardware-back → WebView history;
    `window.print()` does not work in a WebView (label printing stays a
    desktop task; add an "open in browser" escape hatch); file downloads
    (CSV/backup/`.bin` from `/nfc/encode`) need a download handler;
    self-signed-HTTPS servers fail TLS — recommend plain HTTP on the LAN or
    real certificates (Let's Encrypt, Tailscale) rather than shipping a
    cert-trust bypass.
16. **Passkeys / WebAuthn in the WebView.** Android WebView keeps `navigator.
    credentials` disabled unless the embedder opts in via androidx.webkit's
    `setWebAuthenticationSupport`; `react-native-webview` does not expose it,
    so it is patched on (`patches/react-native-webview+*.patch`). Use
    `WEB_AUTHENTICATION_SUPPORT_FOR_APP` — the mode Android documents for
    non-browser apps. `FOR_BROWSER` is only for privileged browser apps and
    makes the ceremony fail with "an unknown error"; that was the initial bug.
    FOR_APP requires the relying party's domain to host a Digital Asset Links
    file authorizing this app + its signing cert (see `mobile/README.md` →
    Passkeys; the Mobile APK workflow prints the fingerprint + a ready
    `assetlinks.json`). The file must sit at the **exact RP-ID hostname**
    (no parent-domain fallback, no redirects, `application/json`, publicly
    trusted TLS); Authelia's RP ID is the portal's exact hostname (from
    `X-Forwarded-Host`, not configurable). To reduce the friction: the server
    serves its own `/.well-known/assetlinks.json` (released fingerprint +
    `SPOOLMAN_ANDROID_CERT_FINGERPRINTS` extras — `spoolman/assetlinks.py`),
    so the RP-is-Spoolman case is zero-config, and the app's ⚙ → *Passkey
    setup* assistant (`src/screens/PasskeySetupModal.tsx`) shows the installed
    APK's real fingerprint (local Expo module `modules/app-signing`) and
    verifies the hosted file with concrete pass/fail reasons. Caveats: the
    patch is pinned to the library version (re-run
    `npx patch-package react-native-webview` after a bump); needs a recent
    Android System WebView and on-device verification; `mediation:
    "conditional"` is unsupported in WebView; iOS WKWebView passkeys are a
    separate, untried path.
17. **In-app self-update (Android).** The app polls
    `releases/latest` on launch and offers to download + install a newer
    `spoolman-companion-*.apk` through the system installer
    (`REQUEST_INSTALL_PACKAGES`; the user grants "install unknown apps" once).
    The release APK's version is stamped from the git tag at build time
    (`mobile-apk.yml`) so `nativeApplicationVersion` is comparable to the
    release tag — without that stamp a released build reads `0.1.0` and would
    self-nag forever. Obtainium remains the zero-code alternative. iOS is out
    of scope (no sideload install path).

## Roadmap & effort (solo-maintainer person-days)

| Phase | Contents | Estimate |
|---|---|---|
| **P0 — Android PoC** | Expo prebuild app: one server profile, WebView + token injection, camera scan → shared parser → navigate, NDEF + NTAG213 raw read → `/nfc/lookup` → navigate. Goal: tap a TigerTag against a plain-HTTP LAN server and land on the spool page. | 4–6 pd |
| **P1 — v0 on both platforms** | Server profiles + secure token storage + login/probing onboarding; retail-barcode flow; NfcV + MIFARE Classic reads (Android); iOS port (ATS, Core NFC sessions); back-button/downloads/open-in-browser polish; Android CI + GitHub Releases/Obtainium; TestFlight. | 15–20 pd |
| **P2 — v1 bridge** | `nativeBridge.ts` + protocol + contract tests; scan-pipeline refactor; phone mode in the NFC scan/bind/write modals incl. verified raw NTAG writes; `apiToken.ts` hook; i18n. | 8–10 pd |
| **P3 — v2 niceties** | Pairing QR, `web+spoolman:` OS handlers, Android tap-to-open, quick-actions on `/spool/{id}/use`, optional server mDNS. | 7–10 pd |
| Ongoing | Store/toolchain upkeep | ~1–2 pd/quarter + fees |

Roughly **6–8 focused person-weeks** to a polished v1 on both platforms,
front-loaded so Android users get value after about two weeks.

## Verdict

**Go — as a React Native shell, Android first.** The hard part is already
built and tested on the server: `/nfc/lookup`'s raw-dump auto-detection, bind,
create-from-tag and encode were designed for external readers, and a phone is
the best external reader this project will ever have. The genuinely new code
is a thin, low-churn native layer (WebView + camera + NFC); the scan grammar
and TigerTag codec are imported, not reimplemented. The payoff is categorical
rather than incremental: scanning works on default plain-HTTP deployments with
zero TLS setup, iPhones get NFC for the first time (impossible via the web,
ever), and phone-written tags become TigerTag-app-compatible. The costs are
honest but bounded: no Qidi on iOS ever, Apple's fees and review friction argue
for shipping iOS only once native value is unmistakable, and store upkeep is a
permanent small tax with GitHub Releases/Obtainium as the Android escape hatch.
Every layer degrades gracefully against older servers, and the plan can stop
after any phase and still have shipped something strictly better than today.
