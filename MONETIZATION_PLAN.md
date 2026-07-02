# Spoolman NG — Hosted-service & monetization plan

**Date:** 2026-07-02 · **Status:** plan only, nothing here is implemented.

Goal: run Spoolman NG as a paid (and possibly ad-supported) hosted service on a
single VPS (traefik + docker + Authelia already present), with Google / Apple /
Microsoft login — while the open-source project stays **100% compatible with
today's single-user, no-auth deployments**. Every released image must keep
working exactly as it does now for the Klipper/LAN crowd.

This document extends `MASTERPLAN.md` (§7 security posture, §8 sustainability)
with the concrete architecture, code changes, infrastructure, billing, and
sequencing needed. Same conventions: **P0–P3** priority, rough effort,
acceptance criteria per work item.

---

## 0. Executive summary

1. **Split the work into three tracks.** Track 1 (auth foundation in core) is
   no-regret open-source work that both deployment models need and that
   self-hosters have asked for anyway. Track 2 (hosted MVP) runs unmodified
   Spoolman containers — one per customer — behind traefik with scale-to-zero,
   and lives in a **private** ops/portal repo. Track 3 (native multi-tenancy in
   core) is only built if the MVP proves ≳100 people will pay.
2. **Compatibility is guaranteed by defaulting everything off.** A single
   `SPOOLMAN_AUTH_MODE` env var, default `none`, gates all auth behavior. Same
   image, same tags, same API paths, same DB schema semantics in `none` mode.
   No separate "cloud" image is required for Tracks 1–2 at all.
3. **Social login = generic OIDC in core + a federating broker on the VPS.**
   Authelia cannot do this: it is an OIDC *provider* only and explicitly does
   not support the relying-party role needed to federate Google/Apple/Microsoft
   ([authelia#4471](https://github.com/authelia/authelia/discussions/4471)).
   Keep Authelia for protecting ops/admin surfaces; add a broker
   (ZITADEL/Authentik/Keycloak, or managed Auth0) as the customer IdP. Core
   Spoolman only ever speaks standard OIDC to **one** issuer, so the broker is
   swappable and self-hosters get "SSO with my own IdP" as a free side effect.
4. **Printer integrations can't send auth headers, so don't rely on headers.**
   Moonraker's `[spoolman]` section is configured with a bare `server` URL (plus
   `sync_rate`) and has no header/token option
   ([moonraker docs](https://moonraker.readthedocs.io/en/latest/configuration/)).
   The compat mechanism is a **secret base-URL token** (`https://host/u/<token>/api/v1/…`)
   that works with every URL-configured client (Moonraker, OctoPrint-Spoolman,
   Home Assistant, MCP server), alongside standard `Authorization: Bearer` for
   clients that can send it. (This corrects MASTERPLAN §7's assumption that
   both integrations support configurable headers — Moonraker does not.)
5. **Be honest about ads: skip them.** The audience is self-hosting 3D-printing
   hobbyists with ad blockers, on a logged-in utility they glance at. Display
   ads would earn cents and cost GDPR consent plumbing. The realistic revenue
   mix is freemium subscriptions (+ makerspace/team tier later) and optional
   filament-reorder **affiliate links**, which are a genuinely useful feature
   rather than an ad.

---

## 1. Constraints & non-negotiables

- **The LAN deployment is the product's soul.** `docker run` +
  `ghcr.io/sherrmann/spoolman:latest` with zero config must behave exactly as
  today, forever. Auth is opt-in; hosted-service code never activates without
  explicit env config.
- **One codebase, one image** for everything open-source. Runtime flags, not
  build variants — otherwise the release pipeline (`ci.yml` multi-arch builds,
  QEMU smoke tests, Moonraker update manager, CalVer tags) forks in two and
  doubles maintenance.
- **Commercial glue stays out of the OSS repo.** Stripe/Paddle code, the signup
  portal, provisioning scripts, ToS/privacy pages, and pricing live in a
  private repo that composes *around* the published image. MIT licensing makes
  the hosted service legal either way, but keeping billing out of core avoids
  burdening every self-hoster's image with it and keeps the fork's OSS story
  clean.
- **API surface does not change shape.** Tenancy must come from *auth context*
  (who is calling), never from new URL structures or request fields — that is
  what keeps every existing integration working with, at most, a token pasted
  into its URL or header.
- **Branding:** MIT covers the code, not the goodwill in the name. The fork is
  already "Spoolman NG"; the paid service should use a clearly distinct product
  name/domain (working title needed) that *mentions* Spoolman compatibility
  rather than trading on the name.

## 2. Market reality check (before writing any code)

**Who would pay?** Spoolman's core users run Klipper on a LAN — they self-host
by identity and already have the hard part (a Pi) running. The plausible paying
segments are: (a) multi-printer households who want one inventory reachable
from everywhere without VPN/reverse-proxy homework, (b) OctoPrint/Bambu-adjacent
users with no always-on server, (c) **makerspaces and print farms** — shared
inventory, several printers, multiple members — who are also the segment that
genuinely needs accounts/roles, and (d) phone-first users who mainly want the
QR/NFC scan-and-update flow (Web NFC works fine against a cloud instance; USB
NFC readers remain a self-hosted-only feature).

**Competition and price anchor.** Generic managed hosts already run
one-click Spoolman-class pods for roughly $1.50–3/month
([PikaPods](https://www.pikapods.com/)), and SimplyPrint-style cloud print
platforms bundle basic filament tracking. A hosted Spoolman NG therefore can't
price much above **€2–4/month** for individuals; the defensible extras are the
integration ecosystem (Moonraker/OctoPrint/HA point at it natively), NFC/QR
labels, the maintained NG fork itself, and a makerspace tier (€10–20/month)
that no one serves well today.

**Ads, honestly.** Logged-in niche utility + ad-block-saturated audience +
GDPR consent banner + AdSense review of a login-walled app ≈ single-digit
euros/month at any plausible scale. Affiliate links on "spool is nearly empty —
reorder" (Amazon/Prusa/3DJake affiliate programs) fit the product, earn more,
and need no consent management beyond a disclosure line. **Decision proposed:
freemium + affiliate, no display ads.** If ads are still wanted later, they are
a frontend-only feature flag in the hosted build and change nothing below.

**Viability envelope.** At €3/month and the instance-per-tenant model on one
8 GB VPS (~60–100 active pods with scale-to-zero, see §6), the ceiling before
re-architecting is roughly €200–300/month gross. That is beer money, not a
business — which is exactly why Track 3 (native multi-tenancy, thousands of
tenants on the same VPS) exists but is gated on demonstrated demand, and why
Track 1 is scoped to be valuable to the OSS project even if the service never
earns a cent.

- [ ] **Demand probe before building the portal** — P0, ~2 h. Post the idea
  (r/klippers, Discussions, Voron/ERCF discords): "hosted Spoolman NG,
  €3/month, would you?" Collect a waitlist (simple form). Gate Track 2 on ≥50
  signups; gate Track 3 on ≥100 paying. Acceptance: a number, not a feeling.

## 3. Architecture decision: how tenants are isolated

| | **A. Instance-per-tenant** (Track 2) | **B. Native multi-tenant core** (Track 3) |
|---|---|---|
| Core code changes | none beyond Track 1 auth | invasive: every query, WS, settings, quotas |
| Isolation | container + own SQLite volume (strong) | row-level `owner_id` (one bug = cross-tenant leak) |
| Density on 8 GB VPS | ~60–100 active pods (~120–250 MB each), idle pods ≈ 0 with scale-to-zero | thousands (one app + Postgres) |
| Free tier cost | fine *if* scale-to-zero works | near-zero marginal |
| Upgrades | roll N containers (scripted) | one deploy |
| Backups | restic over N SQLite volumes | one Postgres + per-tenant export |
| Integration auth | per-pod subdomain; token optional | secret-URL token / bearer (Track 1) |
| Time to first paying user | ~2–3 weeks after Track 1 token auth | ~2–3 months |
| Risk profile | ops toil grows linearly | correctness risk, permanent tenancy tax on every future feature |

**Decision proposed:** A first, B only behind the demand gate. A is how the
managed-host incumbents run Spoolman today, it satisfies "100% compatible" by
construction (it *is* the single-user deployment, just orchestrated), and its
per-tenant subdomain (`alice.spools.example`) means Moonraker configs need no
token at all if the subdomain itself is treated as the secret + forward-auth
protects the UI. B is a real open-source feature in its own right
(families/makerspaces keep asking upstream for multi-user), so if built it
ships in core as an experimental flag — not as proprietary code — and the
hosted service simply becomes its first serious user.

## 4. Identity: Google / Apple / Microsoft login

**Core principle:** Spoolman core implements exactly one thing — a standard
**OIDC relying party** (Authorization Code + PKCE) against a single
configurable issuer, plus local sessions. All social federation happens in a
broker, so core never contains Google/Apple/Microsoft-specific code.

**Broker options for the VPS (customer IdP, coexisting with Authelia):**

| Broker | Social federation | Apple support | Footprint / notes |
|---|---|---|---|
| **ZITADEL** | built-in | built-in template | Go, ~½ GB with its Postgres; nicest Apple path |
| **Authentik** | built-in sources | built-in (Apple OAuth source) | Python, ~700 MB+; popular in homelab |
| **Keycloak** | built-in brokers | needs community extension | JVM, heaviest; most battle-tested |
| **Auth0 / Clerk (managed)** | turnkey | turnkey | zero ops, free tier ≤ ~25k MAU; data leaves the VPS |
| In-app `authlib` (no broker) | 3 providers hand-wired in core | manual (JWT secret rotation) | no extra container, but social code lands in core — rejected by the core principle above |

**Decision proposed:** ZITADEL (or Auth0 if ops minimalism wins) at
`id.<domain>`. **Authelia stays** exactly where it is — protecting grafana,
portainer, the provisioning portal's admin side — it just isn't the customer
IdP, since it deliberately doesn't do the RP role
([authelia#4471](https://github.com/authelia/authelia/discussions/4471)).

**Apple caveats to budget for (P1, recurring):** Sign in with Apple requires a
paid Apple Developer Program membership (~$99/year), a Services ID + private
key, and client secrets that are JWTs valid ≤ 6 months — so secret rotation
must be automated or calendared. Apple also mandates its branding rules on the
button. Worth it only if the waitlist says so; Google + Microsoft are free and
cover most of the audience. Consider shipping Google/Microsoft first and Apple
on demand.

## 5. Track 1 — auth foundation in core (open source, no-regret)

All gated on `SPOOLMAN_AUTH_MODE` = `none` (default) | `token` | `oidc`.
`none` short-circuits every check at the dependency level — zero behavior
change, zero measurable overhead.

- [ ] **`token` mode: static bearer token(s)** — P1, ~2–3 days (already
  MASTERPLAN §7). `SPOOLMAN_API_TOKEN` (+ `_FILE` variant, matching the
  existing `SPOOLMAN_DB_PASSWORD_FILE` pattern in `spoolman/env.py`); a FastAPI
  dependency on the v1 router (`spoolman/api/v1/router.py`) accepting
  `Authorization: Bearer`, `X-Api-Key`, or `?token=` (query form needed for
  websockets and header-less clients). `/api/v1/health` stays open (the
  Dockerfile HEALTHCHECK depends on it). Acceptance: e2e matrix runs both
  modes; Moonraker/OctoPrint docs updated with the URL-token form.
- [ ] **Secret base-URL token acceptance** — P1, ~1–2 days, with the above. An
  ASGI middleware that recognizes `/u/<token>` in front of the mounted apps,
  validates, strips, and forwards (the machinery mirrors the existing
  `SPOOLMAN_BASE_PATH` handling in `spoolman/main.py`). This single feature is
  what lets `[spoolman] server: https://host/u/<token>` work in Moonraker with
  no Moonraker changes, headers, or VPN. Tokens are revocable; docs must warn
  they appear in logs like any webhook URL. Acceptance: integration smoke test
  drives spool usage through the tokened URL, REST + WS.
- [ ] **(Nice) upstream a `headers:` option to Moonraker's `[spoolman]`** —
  P3, ~1 day + review latency. Removes the URL-token caveat for the biggest
  integration; benefits everyone running any authenticated Spoolman.
- [ ] **`oidc` mode: generic OIDC RP + sessions** — P1, ~1–2 weeks. Env:
  issuer URL, client id/secret, scopes. Authorization-code flow endpoints
  (`/api/v1/auth/login|callback|logout|me`), signed httpOnly session cookie
  (`SameSite=Lax`), CSRF defense for cookie-authenticated mutating requests
  (double-submit or custom-header requirement — the API is currently
  cookie-free so this is new ground), WS auth via session cookie (browsers
  can't set WS headers). In this mode it's still **one user database-wise** —
  OIDC just replaces "no login" with "login", which is precisely the
  "Authelia/Keycloak SSO for my homelab Spoolman" feature self-hosters ask
  for. Acceptance: e2e with a throwaway IdP (dex/mock-oidc) container.
- [ ] **Client: refine `authProvider`** — P1, ~3–5 days, part of the above.
  The SPA already uses refine v5 (`client/src/App.tsx`), which has first-class
  `authProvider` support — implement it against `/auth/me` + login redirect,
  render nothing auth-related when `/api/v1/info` says mode `none`. The mode
  must be runtime-served (extend `/config.js` or `/info`), not `VITE_`-baked,
  so one built client serves all modes.
- [ ] **Managed API tokens (DB-backed)** — P2, ~3–5 days. `api_token` table
  (hashed secret, name, created/last-used, revocation), CRUD endpoints + a
  settings-page UI. In `oidc`/multi-user modes these are per-user; in `token`
  mode this supersedes the single static env token. This is what customers
  paste into Moonraker. Acceptance: revoking a token kills its WS within a
  sync interval.
- [ ] **CI: auth-mode test matrix** — P1, ~2–3 days alongside the first mode.
  Extend the existing e2e jobs with `SPOOLMAN_AUTH_MODE=token` and `oidc`
  legs; add a signal gate asserting mode-`none` runs byte-identical API
  behavior (guards the compatibility promise mechanically).

## 6. Track 2 — hosted MVP on the existing VPS (private repo)

Topology (all compose services behind the existing traefik):

```
traefik (existing)
 ├─ id.<domain>          → ZITADEL (customer IdP; Google/MS/Apple federation)
 ├─ portal.<domain>      → portal service (signup, plan, provisioning, billing)
 ├─ <name>.spools.<domain> → per-tenant spoolman container (official image,
 │                           SQLite volume, forward-auth to IdP for the UI,
 │                           API paths open or token-gated per Track 1)
 └─ ops.<domain>/…       → grafana/portainer/etc. behind Authelia (unchanged)
```

- [ ] **Wildcard DNS + certs** — P0, ~2 h. `*.spools.<domain>` A record;
  traefik DNS-01 challenge for the wildcard cert (HTTP-01 can't do wildcards).
- [ ] **Portal + provisioner** — P0, ~1–2 weeks. Small service (FastAPI, same
  stack as core for familiarity): OIDC login against the broker, "create my
  instance" → docker API: run `ghcr.io/sherrmann/spoolman:<pinned>`, volume,
  traefik labels, forward-auth middleware; suspend/resume/delete; show the
  Moonraker/OctoPrint snippet with the tenant URL. Acceptance: signup → usable
  instance < 60 s, no human involved.
- [ ] **Scale-to-zero for idle pods** — P1, ~2–4 days.
  [Sablier](https://github.com/sablierapp/sablier) as a traefik plugin: idle
  tenant containers stop; first request wakes them (a few seconds — fine for a
  dashboard, and Moonraker retries). This is what makes a free/cheap tier
  affordable on one VPS: idle pods cost disk only. Acceptance: pod stops after
  N min idle, wakes on hit, Moonraker sync survives a wake cycle.
- [ ] **UI auth vs API auth split per pod** — P0, design decision, ~2–3 days.
  Simplest viable: traefik forward-auth (via the broker's proxy/outpost or
  oauth2-proxy) on everything *except* a bypass for `Authorization`/`X-Api-Key`
  headers and `/u/<token>` paths once Track 1 lands; until then, subdomain
  secrecy + forward-auth on the UI with `/api/…` open is the PikaPods-grade
  MVP posture (documented honestly to beta users).
- [ ] **Fleet upgrades** — P1, ~2 days. Script: pull pinned tag → rolling
  restart tenant pods (each runs its own alembic on start, as today per
  `spoolman/main.py` startup) → smoke `/api/v1/health` per pod; staged canary
  tenant first.
- [ ] **Backups & restore drill** — P0, ~2 days. restic (or borg) over all
  tenant volumes + the existing per-pod `POST /api/v1/backup` (SQLite) before
  snapshot; portal button "download my data" using the existing export
  endpoints (`/api/v1/export/…` CSV/JSON). Practice one full tenant restore
  before taking money. Acceptance: documented RPO ≤ 24 h, tested restore.
- [ ] **Migration importer (self-hosted → cloud funnel)** — P1, ~1 week. Today
  core has export but **no import endpoint** — the onboarding story for
  existing users is "upload your SQLite backup / JSON export into your new
  instance." Per-tenant model makes this easy (drop the uploaded spoolman.db
  into the volume after validation + `alembic upgrade`); build it in the
  portal, consider upstreaming a REST JSON-import to core later (P2) since
  self-hosters migrating between DB types want it too. Also the exit door:
  export always works, which is a selling point against lock-in.
- [ ] **Monitoring & paging** — P1, ~2–3 days. Existing Prometheus support per
  pod (`SPOOLMAN_METRICS_ENABLED`) + traefik metrics + uptime-kuma/Gatus on a
  public status page; alert to phone. GlitchTip/Sentry for the portal.
- [ ] **Abuse controls** — P1, ~1–2 days. Signup email verification comes free
  from the broker; traefik rate-limit middleware per tenant host; disk quota
  per volume; auto-suspend pods exceeding CPU/GB (docker limits `mem_limit`,
  `cpus` per pod from day one).

## 7. Track 3 — native multi-tenancy in core (gated: ≥100 paying)

Ships in the **open-source core** behind `SPOOLMAN_AUTH_MODE=multiuser`
(implies `oidc`), because shared-instance multi-user is a long-requested
community feature (households, makerspaces) — the hosted service is just its
biggest deployment. Order of work:

- [ ] **Schema: `user` + ownership columns** — P0, ~1 week. New `user` table
  (id, issuer+subject unique, email, display name, role, plan fields left
  NULL in OSS); nullable `owner_id` FK added to `vendor`, `filament`, `spool`
  (`calibration_session` inherits via filament; `*_field` tables inherit via
  parent) in `spoolman/database/models.py`; `setting` PK becomes
  `(owner_id, key)` — settings like currency, `extra_fields_*`, `locations`
  (see `spoolman/settings.py`) are per-user in multiuser mode. Alembic
  migration backfills a default user (id 1) over existing rows; in `none` mode
  everything keeps writing owner 1 implicitly, so **the schema is identical in
  all modes and the API models never expose `owner_id`**. Tested downgrade
  migration so a hosted DB can step back a release.
- [ ] **Query scoping, mechanically enforced** — P0, ~1–2 weeks. A
  per-request tenant contextvar set by the auth dependency; scoping applied
  centrally via SQLAlchemy `with_loader_criteria` on `Base` (plus explicit
  filters in the handful of raw/aggregate queries under `spoolman/database/`).
  The enforcement is the point: a cross-tenant e2e suite (two users, full CRUD
  + search + export + extra-fields + locations, assert zero bleed) and a CI
  signal gate — this repo's existing mutation-testing/e2e rigor is the reason
  to trust row-level tenancy at all.
- [ ] **Websocket scoping** — P0, ~2–3 days. Prefix the in-process
  subscription tree path with the tenant id inside `spoolman/ws.py`
  (`(tenant, "spool", id)`); client subscribes relative paths as today, server
  derives tenant from the session/token. `none` mode uses the constant default
  tenant — tree behavior byte-identical.
- [ ] **Instance-global endpoints become admin-only** — P0, ~2 days.
  `/api/v1/backup`, `/info` (paths/dirs), `/metrics` (global spool counts —
  keep global, never per-tenant labels: cardinality + leakage), export
  endpoints already per-tenant via scoping. Admin role = first user in OSS,
  ops-only in hosted.
- [ ] **Quotas & plan hooks** — P1, ~3–4 days. Generic per-user limits
  (max spools/filaments/tokens) enforced at create endpoints, configurable via
  env/DB, unlimited by default in OSS. The hosted billing service flips them
  per plan; core stays payment-ignorant.
- [ ] **Known limits, documented not solved** — P2. Integer PKs leak global
  counts across tenants (acceptable; document). The WS manager and NFC
  auto-create lock are in-process (`spoolman/ws.py`,
  MASTERPLAN §7) — multiuser mode therefore stays **single-worker**; measured
  headroom (10k-spool dashboard ≈ 43 ms) suggests one worker + Postgres
  carries thousands of light tenants. Redis pub/sub fan-out is the
  scale-out escape hatch, deliberately out of scope until it hurts.
- [ ] **Hosted cutover** — P1, ~1 week. Importer walks tenant SQLite volumes
  into one Postgres with owner mapping; per-tenant subdomains 301 to the
  single host; per-tenant tokens carry over. Instance-per-tenant remains the
  "dedicated instance" premium tier (it's also the only tier that can offer
  server-side USB NFC — irrelevant in cloud — and custom versions).

## 8. Billing, plans, and the ads question

- [ ] **Merchant setup decision** — P0, ~1 day research + setup. Two viable
  routes for an EU seller: **Stripe** (Checkout + Billing portal + Stripe Tax;
  you are seller of record → OSS/VAT registration duties, e.g. German
  Kleinunternehmer threshold vs. VAT-OSS) or a **merchant-of-record**
  (Paddle / Lemon Squeezy: they owe the VAT, ~5%+ fees, near-zero admin).
  Recommendation: **MoR first** — at €200/month scale, VAT paperwork costs
  more than the fee delta. Not legal advice; confirm with a tax person.
- [ ] **Plan matrix** — P1, ~1 day to configure once portal exists.
  *Free/trial:* 1 instance, scale-to-zero aggressive, ~50 spools, community
  support — exists to feed the funnel and the demand gate. *Plus €3/mo or
  €30/yr:* unlimited spools, always-warm optional, API tokens, label/NFC
  features. *Makerspace €15/mo (Track 3 or dedicated pod):* multiple members,
  shared inventory, roles. Lifetime deal (€60–90) as launch promo — this
  audience loves buying lifetime.
- [ ] **Billing ↔ provisioning glue** — P0, ~3–5 days. Webhook consumer in the
  portal: `checkout.completed` → provision/upgrade; `payment_failed` →
  dunning (MoR handles emails) → suspend after grace (stop container, keep
  volume 90 days) → delete with prior notice. Acceptance: every state
  transition exercised in test mode before launch.
- [ ] **Ads: formal no-go, affiliate yes** — P2, ~2–3 days when wanted.
  Decision recorded per §2. Affiliate implementation is a hosted-frontend
  feature: reorder link on low/empty spools built from vendor + article number
  (both already in the data model), disclosure line, per-user opt-out. Zero
  core changes; zero consent-management if no tracking pixels are used.
- [ ] **In-app donation/sponsor link for OSS** — P3, ~1 h. Aligns with
  MASTERPLAN §8's open FUNDING.yml decision; the hosted service *is* the
  funding story, and the README should say so plainly ("run it yourself free,
  or pay us to run it").

## 9. Compatibility guarantee & release engineering

The promise, spelled out so it can be tested and advertised:

1. **Default behavior is frozen.** `SPOOLMAN_AUTH_MODE=none` is the default in
   every release and behaves exactly like today — same endpoints, same
   schemas, same websockets, no login, no cookies. CI enforces this with the
   mode-`none` parity gate (§5).
2. **Same images, same tags.** `ghcr.io/sherrmann/spoolman` /
   `cookiemonster95/spoolman`, `latest` + CalVer, amd64/arm64/armv7, Moonraker
   update manager untouched. No separate single-user image is *needed*; if
   optics demand it, publish an alias tag (e.g. `:selfhost`) pointing at the
   same digest rather than a second build.
3. **API models never grow tenancy fields.** `owner_id` is server-side only;
   integrations authenticate (or don't, in `none` mode) and see exactly the
   API they see today.
4. **DB stays portable.** SQLite remains the default and fully supported in
   all non-hosted modes; migrations backfill the default user and ship tested
   downgrades (§7). A DB created today keeps upgrading forever.
5. **Docs split cleanly.** README keeps leading with the LAN quick-start;
   auth modes live in a new `docs/authentication.md`; the hosted service gets
   marketing pages in the private repo, plus one README line, and the
   SECURITY.md threat model gains an "authenticated modes" section instead of
   being rewritten.

## 10. Legal & ops checklist (hosted service only)

- [ ] **P0:** ToS + privacy policy + (if DE/AT) Impressum; GDPR basis mapping
  (account data, spool data, backups off-site, broker + payment processor as
  processors → DPAs, all standard paperwork with Stripe/Paddle/ZITADEL cloud
  or self-hosted). Account deletion must cascade: pod/rows + backups rotation
  window disclosed. Data export already exists (CSV/JSON) — advertise it.
- [ ] **P0:** Separate legal entity decision / hobby income declaration
  (jurisdiction-dependent; MoR shrinks this to income tax only). Not legal
  advice.
- [ ] **P1:** Support channel (email + GitHub Discussions category), response
  expectation stated (best-effort, this is a one-person service — say so),
  status page (§6), incident template.
- [ ] **P1:** Security posture page: what "beta" means, single-operator
  disclosure, backup cadence, disclosure policy reuse from SECURITY.md.
- [ ] **P2:** Trademark/name search for the service brand; check Apple/Google
  OAuth branding-compliance requirements during app registration (Apple
  reviews the Services ID domain).

## 11. Sequencing & effort summary

| Phase | Contents | Effort (1 person) | Gate to proceed |
|---|---|---|---|
| 0. Probe | §2 waitlist post, §8 merchant research, name pick | ~1 week part-time | ≥50 waitlist |
| 1. Auth core | §5: token mode → secret-URL → OIDC RP + authProvider → CI matrix (ships to OSS regardless) | ~3–5 weeks | — (no-regret) |
| 2. Hosted MVP | §6 portal/provisioner/sablier/backups + §8 billing glue + §10 P0 legal | ~3–4 weeks | beta: 10–20 users on it |
| 3. Launch | pricing live, announcement (pairs with MASTERPLAN §8 outreach), affiliate v1 | ~1 week | ≥100 paying? |
| 4. Native MT | §7 in core as experimental → hosted cutover | ~6–8 weeks | only if gate 3 passed |

Total to a launched paid service: **~2–3 months of focused solo work**, of
which the first ~40% (Track 1) is straight open-source improvement the fork
should arguably do anyway (MASTERPLAN already priced the first slice of it).

## 12. Open questions for the maintainer

1. **Demand gate numbers** — are 50 waitlist / 100 paying the right bars, and
   is €200–300/month at the instance-per-tenant ceiling worth the ops
   commitment if Track 3 never triggers?
2. **Broker choice** — ZITADEL self-hosted (all data on the VPS, more ops) vs
   Auth0 free tier (zero ops, external dependency)? Apple login day one
   (+$99/yr and rotation chores) or on demand?
3. **Brand name** for the paid service (blocks domain, OAuth registrations,
   ToS).
4. **Free tier** — offer one at all, or paid-only with a 14-day trial?
   (Scale-to-zero makes free *possible*, not free.)
5. **Where does the portal live** — private repo as proposed, or public
   sans-secrets (marketing value, contribution surface, but exposes pricing
   logic and makes "compatible fork of the service" trivial)?
6. **Moonraker upstream PR** (headers option) — worth doing early for goodwill
   and to advertise Spoolman NG in Moonraker's docs, even though the
   secret-URL pattern already solves it?
