# Spoolman NG — Fork Assessment & Roadmap TODOs

**Date:** 2026-07-01 · **Scope:** all work since upstream v0.23.1 (commit `eafbc64`, Feb 2026; upstream abandoned ~March 2026) through `d34402f` (PR #36).

This document assesses the ~36 PRs of fork work and lists the TODOs needed to make
Spoolman NG a solid long-term home for a large user base.

---

## 1. What has been done since March (state of the fork)

All fork work landed 2026-06-30 → 2026-07-01, PRs #2–#36, on top of upstream v0.23.1.

### Features
- **Upstream community PRs merged** (#2): extra-field filter/sort, 3D Filament Profiles
  import, weight-delta spool events, calibration sessions (new `calibration_session` /
  `calibration_step_result` tables).
- **Redesigned home dashboard** (#3): KPI cards + inventory analytics (client-side aggregation).
- **Filament label printing** (#4): label templates, QR codes, QR scanning.
- **NFC spool identification** (#5, #13): TigerTag, OpenPrintTag, QIDI codecs; Web NFC and
  server-side USB reader; `POST /api/v1/nfc/*` endpoints incl. external lookup for Klipper
  daemons; enabled on all architectures including armv7.

### Fork infrastructure
- **Identity**: rebranded "Spoolman NG", drop-in compatible with upstream (#8, #12).
- **Releases**: CalVer (`2026.6.x`), automated release workflow, release ZIP +
  `release_info.json`, Moonraker one-click updates pointing at the fork (#8, #10, #11).
- **Images**: multi-arch (amd64/arm64/armv7) published to `ghcr.io/sherrmann/spoolman` and
  Docker Hub `cookiemonster95/spoolman` with `:latest`/`:edge`/`:sha-*` tags (#6, #7).
- **Native install**: one-line `scripts/install.sh` (systemd, uv), Fedora support, armv7
  build tools (#11, #12).

### Maintenance & quality
- **Dependency refresh**: Node 22 toolchain, Debian trixie base, Starlette 1.x
  (CVE-2026-48710/48817/48818/54282/54283), hishel 1.x, Vite 8, TypeScript 6, i18next 26,
  `path-to-regexp` 8.4.2 override (ReDoS), backend dep refresh (#15–#25).
- **Bug fixes**: PWA/service-worker base-path correctness (manifest `start_url`/`scope`,
  SW registration path, navigation precache bug), `useSavedState` localStorage poisoning
  (#26–#29).
- **Testing** (#30–#36): ~431 behavioral tests — backend unit + 4-DB integration matrix
  (SQLite/Postgres/MySQL/CockroachDB), Vitest+RTL client tests, Playwright e2e (PWA flows +
  20 whole-app journeys), mutation-testing gates (Stryker ≥90 hard gate on crown-jewel
  modules, ~97% actual; mutmut advisory for Python codecs), CodeQL, hadolint.
  `TESTING_STRATEGY.md` / `TESTING_CANDIDATES.md` document the approach honestly.

### Verdict on the work so far

The engineering quality is high. CI on `master` is green, the release pipeline is fully
independent of upstream, migrations are linear and safe, new API endpoints stay under
`/api/v1` and remain drop-in compatible with Moonraker/OctoPrint/Home Assistant, N+1s are
avoided (`contains_eager`/`selectinload`), and the test/mutation gates are unusually strong
for a project of this size. **The technical base for a fork is sound.** The gaps are almost
all in *community-facing* areas: runtime coupling to abandoned upstream infrastructure,
translations, governance, and documentation.

---

## 2. Already in good shape — no action needed

- Release automation, CalVer, GHCR/Docker Hub publishing, Moonraker update path.
- `scripts/install.sh`, `docker-compose.yml`, README install instructions — all point at the fork.
- API docs published independently to `sherrmann.github.io/Spoolman` (`apidocs.yml`).
- Issue templates are neutral (no upstream references); dependabot configured for pip + npm.
- Migration chain linear; calibration tables use proper FKs with `ondelete="CASCADE"`.
- No TODO/FIXME debt introduced by the fork; known bugs are pinned by tests and documented.
- No open issues/PRs backlog.

---

## 3. TODOs

### P0 — Decouple from abandoned upstream infrastructure (breaks users if upstream rots)

1. **SpoolmanDB default URL** — `spoolman/externaldb.py:22` and `.env.example:58` default to
   `https://donkie.github.io/SpoolmanDB/`. This is a *runtime* dependency on the abandoned
   upstream's GitHub Pages: if the repo is archived/deleted, filament sync breaks for every
   default install, and the data will go stale regardless.
   ⏳ *In progress:* `sherrmann/SpoolmanDB` has been forked, but its GitHub Pages is not
   serving yet (`https://sherrmann.github.io/SpoolmanDB/filaments.json` → 404). Enable
   Actions + Pages on the fork and run its deploy workflow, then switch the default URL
   here (`externaldb.py`, `.env.example`, README, CONTRIBUTING).
2. **Translation pipeline** — README points contributors to upstream's Weblate project
   (`hosted.weblate.org/projects/spoolman/`), which feeds the *upstream* repo. The fork
   currently has **no way to receive translation updates**.
   → Register a Spoolman NG project on Hosted Weblate (free for libre projects) or document
   a PR-based translation workflow; update README.
3. ✅ **Translate the fork's new features** — *done:* all 27 locales seeded with AI
   translations to 99–100% key coverage (from ~68%; `et`/`hi-Latn` from <15%, both now
   selectable in the UI for the first time). Existing human translations untouched;
   placeholders validated programmatically. Native-speaker review remains welcome via PRs.
   `client/scripts/check-i18n.js` reports per-locale coverage on every CI run.
4. **In-app links point at upstream** —
   ✅ *Done:* the help page now links to this repo's Integrations section.
   *Open:* `client/src/components/header/index.tsx:62` (Ko-fi → `ko-fi.com/donkie`) —
   decide deliberately whether the donation link should keep honoring the original author,
   point at the fork maintainer, or be removed (align with FUNDING.yml, TODO 9).
5. **Docs/wiki story** — README links installation, Prometheus, and general docs to the
   upstream wiki (`README.md:24,45,114`), which the fork cannot edit and which may vanish.
   → Mirror the load-bearing wiki pages (Installation, Integrations, Filament Usage
   History) into `docs/` or the fork's wiki and relink. Keep an attribution note.

### P1 — Community & governance (needed before inviting many users/contributors)

6. ✅ **CONTRIBUTING.md** — *done:* dev setup (uv, npm, lefthook), PR process, testing
   expectations, translation and SpoolmanDB contribution guidance.
7. ✅ **SECURITY.md + README security section** — *done:* threat model (no auth by
   design, trusted-LAN model; `nfc/write` and `auto_create` raise the stakes),
   reverse-proxy/VPN guidance for internet exposure, private reporting via GitHub
   security advisories.
8. ✅ **Issue Manager workflow removed** — the scheduled run failed every night because
   `tiangolo/issue-manager@0.8.0`'s Docker image is broken
   (`ModuleNotFoundError: typing_extensions`), and auto-closing issues is premature for a
   young fork. Reintroduce a maintained action later if triage volume warrants it.
9. **FUNDING.yml** — currently the untouched GitHub placeholder. Fill in the fork's funding
   (consistent with whatever decision is made for the in-app Ko-fi link, TODO 4).
10. **Bus factor / ownership** — 100% of fork commits are one person; Docker Hub publishing
    runs under the personal `cookiemonster95` account (`ci.yml:653,666`). Consider a GitHub
    org (also gives the fork a neutral home if other maintainers join), a Docker Hub org or
    GHCR-only distribution, and at least one co-maintainer with release rights.
    ✅ *Done:* PR template with tests/i18n/API-compat/migration checklist.
11. **Upstream backlog triage** — upstream had ~830 issues/PRs; the fork merged four
    high-value PRs. Sweep upstream's open PRs/issues once for remaining well-tested,
    popular changes (and known bugs with fixes attached) worth adopting, and say publicly
    (README/Discussions) that this is where such contributions should now go.
12. **Attribution hygiene** — `pyproject.toml:7` still lists Donkie as author (fine as
    attribution; add maintainers field), and the release-notes template correctly credits
    upstream. Keep, but make the "continuation of an unmaintained project" wording
    consistent everywhere (README does this well already).

### P2 — Hardening & known bugs (tracked, not yet fixed)

13. **OpenPrintTag UUID bug** — `effective_instance_uuid`/`effective_brand_uuid` pass
    `bytes` to `uuid.uuid5` and raise `TypeError`; behavior is pinned by tests awaiting a
    deliberate fix (see `TESTING_STRATEGY.md` §8).
14. **Low-stock sort/filter inconsistency** — the dashboard's low-stock sort comparator
    uses a different weight-fallback chain than the filter; also pinned, not fixed.
15. **Abuse-resistance for `auto_create`** — add a duplicate-guard test (N forged tags with
    identical material/color → ≤1 spool) and consider a simple rate limit on
    `/api/v1/nfc/lookup`.
16. **DB-level cascade on `*Field` tables** — Vendor/Filament/SpoolField FKs rely on
    ORM-level cascade only; add a migration setting `ondelete="CASCADE"` for
    defense-in-depth against direct SQL deletes.
17. **Dashboard analytics at scale** — aggregation is client-side over the full spool list;
    fine for <1k spools, worth a benchmark at 5–10k and, if needed, an optional
    server-side `/api/v1/spool/analytics` aggregate endpoint.

### P3 — Polish / long tail

18. **e2e long tail** from `TESTING_STRATEGY.md` §8 "Remaining": calibration wizard,
    print-dialog permutations, 3DFP import journey, list filter/sort, locations
    drag-and-drop, error/empty branches, i18n `<Trans>` rendering.
19. **Community channels** — enable GitHub Discussions (or link a Matrix/Discord) so
    support questions don't all become issues; announce the fork where users will look
    (upstream issue tracker if possible, r/klippers, Moonraker/Fluidd/Mainsail docs which
    currently link upstream).
20. **Integration ecosystem outreach** — OctoPrint-Spoolman, Home Assistant integration,
    OctoEverywhere etc. target upstream's API (still compatible today); longer-term, get
    the fork listed in their docs as the maintained endpoint.

---

## 4. Suggested sequencing

- ✅ **Done on this branch:** issue-manager workflow removed; help link points at the
  fork; SECURITY.md + README security section; CONTRIBUTING.md; PR template; per-locale
  i18n coverage report in CI; README translation/SpoolmanDB notes corrected; all 27
  locales seeded to 99–100% coverage (et and hi-Latn newly enabled in the UI).
- **Week 1 (P0 core, needs maintainer/external access):** enable Actions + Pages on the
  forked sherrmann/SpoolmanDB and switch the default URL; Weblate later (AI-seeded
  translations in place meanwhile); Ko-fi link deliberately kept on the original author
  for now — revisit together with FUNDING.yml.
- **Weeks 2–3 (P1):** mirror wiki docs.
- **Week 4+ (P2/P3):** fix the two pinned bugs, cascade migration, auto_create guard,
  upstream backlog sweep, community channels, integration outreach.
