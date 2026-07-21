# Local Deployment-Scenario Harness — Design

**Date:** 2026-07-21
**Status:** Approved design, pending implementation plan
**Topic:** A local, parallel runner that brings up realistic Spoolman deployment
configurations (auth, reverse proxy, non-x86 arch, DB backend), asserts against them
with the full existing test suites, and can leave any scenario standing for manual use.

---

## 1. Motivation

Spoolman ships into a wide envelope of deployment shapes: with or without API auth, behind
nginx / traefik / Caddy at a sub-path or root, on amd64 / arm64 / armv7, against four DB
backends. Today those axes are covered thinly and slowly:

- **Auth** — only unit-tested (`tests/test_auth.py`); nothing brings up the *real* app with
  a token enforced end-to-end.
- **Reverse proxy** — `tests_deployment/playground/` exercises the traefik sub-path case
  interactively, but there is no lean, on-demand harness for the proxy/auth combinations that
  bite in the field.
- **Arch** — armv7/arm64 are CI-only, under QEMU, and only smoke-tested against
  `/api/v1/health` (SQLite). No behavioral coverage.
- **Speed** — the relevant CI jobs (`e2e`, `build-arm64`, `build-armv7`, integration `test`
  matrix) are slow on GitHub runners. The developer's local machine is powerful and can run
  many stacks in parallel.

**Goal:** a bespoke local runner that treats each realistic deployment as a first-class
**scenario** — brings the stack up, runs the *full* existing assertion suites against it, and
tears it down — parallelised across the machine, with any scenario optionally left running for
a human to poke at or hand to a tester. Automation and manual QA share one scenario definition,
so the thing you click through is the thing the harness gates on.

## 2. Non-goals

- **Not** wiring this into per-PR CI now. The catalog is kept import-clean so a future
  nightly / `workflow_dispatch` job is a small add, but no workflow ships in this work.
- **Not** replacing `tests_integration`, `tests_deployment`, or the existing e2e — this reuses
  them as assertion engines and orchestration patterns.
- **Not** a full combinatorial matrix by default — hybrid (curated core + opt-in expansion).
- **Not** introducing a `docker compose` v2 dependency (this machine has only v1
  `docker-compose`; the driver owns orchestration and calls v1 under the hood).

## 3. Architecture overview

A new `tests_scenarios/` directory sibling to `tests_integration/` and `tests_deployment/`,
plus a `poe scenario` driver task backed by a bespoke Python CLI. The CLI owns the full
lifecycle (build → up → wait → assert → down), schedules scenarios in parallel with a worker
pool, and invokes the existing `tests_integration` suite and Playwright e2e as its assertion
engines.

### 3.1 Directory layout

```
tests_scenarios/
  __main__.py            # CLI entrypoint (argparse): list / up / down / test / test-all / ps / logs
  catalog.py             # Scenario dataclass + CORE list + expansion axes
  runner.py              # lifecycle: build, up (dynamic ports + unique project), wait-healthy, down
  scheduler.py           # parallel worker pool, per-scenario weight, resource caps
  assertions/
    integration.py       # invoke tests_integration suite against a scenario URL+token
    e2e.py               # invoke Playwright against an external scenario stack
    contract.py          # lean smoke contract (health, CRUD round-trip, auth, sub-path, WS)
  proxies/
    nginx/               # sub-path, root, X-Forwarded-*, TLS config templates
    traefik/             # reuse/adapt the playground's traefik labels
    caddy/               # Caddyfile templates
  compose/
    proxy-overlay.yml.j2 # proxy sidecar overlay, rendered per scenario
    (reuses tests_integration/docker-compose-<db>.yml for the DB + server)
  seed/
    sample.py            # optional sample dataset loader
  README.md
```

### 3.2 CLI surface

```
poe scenario list                       # catalog + tags + which axes each scenario pins
poe scenario up <name>                  # bring up, seed, print URL+creds, leave running
poe scenario down <name> | --all        # tear down (unique compose project → no collisions)
poe scenario test <name> [--keep]       # up → assert → down (--keep leaves it up on finish)
poe scenario test-all [-j N] [filters]  # parallel across the machine
poe scenario ps                         # list running scenario stacks + their URLs
poe scenario logs <name>                # tail a running stack
```

`test-all` filters: `--tags core,auth`, `--db all|sqlite,postgres,...`,
`--arch amd64,arm64,armv7`, `--proxy none,nginx,traefik,caddy`, `--full/--quick`.

## 4. Scenario model

A scenario is one point in a small parameter space, declared as a dataclass in `catalog.py`:

| Axis | Values | Mechanism |
|---|---|---|
| `db` | sqlite · postgres · mariadb · cockroachdb | reuse `tests_integration/docker-compose-<db>.yml` |
| `auth` | none · token · users | `SPOOLMAN_API_TOKEN` (token, admin) / `SPOOLMAN_AUTH_SECRET` + `POST /auth/login` (users) |
| `proxy` | none · nginx · traefik · caddy (× subpath/root/forwarded/TLS variants) | proxy sidecar overlay rendered from `proxies/` |
| `arch` | amd64 · arm64 · armv7 | buildx `--platform` + QEMU/binfmt; server image built per arch |
| `seed` | empty · sample | `seed/sample.py` against the running API |

Each scenario resolves to a concrete tuple the runner and assertion engines consume:
`(env vars, proxy overlay or none, target base-URL incl. sub-path, auth token or login creds)`.

## 5. Catalog: curated core + opt-in expansion

### 5.1 Core (always run on `test-all`, native arch, parallel)

1. **`sqlite-bare`** — baseline: SQLite, no proxy, no auth. Fastest sanity stack.
2. **`postgres-auth-nginx-subpath`** — the archetypal self-host: Postgres + `SPOOLMAN_API_TOKEN`
   + nginx serving under `/spoolman` with `X-Forwarded-*`. Exercises the combination users most
   often misconfigure.
3. **`mariadb-traefik-root`** — MariaDB (REPEATABLE READ, catches concurrency bugs SQLite/PG
   miss) behind traefik at domain root.
4. **`cockroach-users-caddy-subpath`** — user accounts (`SPOOLMAN_AUTH_SECRET` + login flow)
   behind Caddy under a sub-path, on CockroachDB (SERIALIZABLE).
5. **`armv7-sqlite`** — real armv7 image under QEMU; full suite (see §7).

This core touches every DB, every auth mode, all three proxies, and the armv7 arch at least once.

### 5.2 Expansion (opt-in)

Any axis widened on demand via filters — e.g.
`poe scenario test-all --arch armv7,arm64 --db all --proxy nginx,caddy`. Expansion generates
the cross-product of the requested axes (skipping meaningless combos), tags each generated
scenario, and schedules it through the same pool. This keeps the default run sane while giving
unlimited depth when the machine is idle.

## 6. Orchestration & parallelism

The driver sidesteps the no-`compose`-v2 constraint by owning orchestration:

- **Isolation:** each scenario gets a unique compose **project name**
  (`spoolman-scn-<name>-<shortid>`) and **dynamically allocated host ports** (bind `:0`, read
  back the assigned port) so any number run concurrently and none collide with a running
  `playground` or another scenario.
- **Compose:** the DB + server come from the existing `tests_integration/docker-compose-<db>.yml`
  files; a rendered `proxy-overlay.yml` adds the proxy sidecar and rewires the published port to
  the proxy. Brought up with `docker-compose` **v1** (`-p <project> -f base -f overlay up -d`).
- **Readiness:** wait on `/api/v1/health` through the *final* ingress (proxy if present), with a
  generous timeout for QEMU arches.
- **Scheduling:** a worker pool with `-j N` (default = a sane fraction of cores). Each scenario
  carries a **weight**; QEMU/arm scenarios are heavy so the scheduler won't oversubscribe CPU
  when several emulated stacks run at once.
- **Teardown:** always `down -v` for the project on completion (unless `--keep`), including on
  failure, so the machine doesn't accumulate stacks. `ps`/`down --all` clean up strays.
- **Build caching:** per-arch images built once and reused across scenarios sharing that arch;
  buildx registry/local layer cache keeps armv7 rebuilds cheap.

## 7. Assertion engines (the seams)

Per approval, every scenario runs the **full `tests_integration` suite + Playwright e2e** — even
under QEMU. Both engines currently assume they *own* the server and that there is *no* auth, so
each needs a small seam:

### 7.1 Integration suite seam

`tests_integration/tests/conftest.py` today hardcodes `URL = "http://spoolman:<port>"` and sends
no `Authorization` header. Changes (backward-compatible defaults):

- `URL` from `SPOOLMAN_TEST_URL` (default: current value) — lets the suite target any scenario's
  ingress URL, sub-path included.
- When `SPOOLMAN_TEST_TOKEN` is set, the shared httpx client injects
  `Authorization: Bearer <token>` on every request, and WS fixtures append `?token=<token>`.
- For `users` scenarios the token is obtained by calling `POST /auth/login` first, then reused.

With those seams the entire existing suite runs unmodified against any scenario URL+auth+proxy.

### 7.2 Playwright seam

`client/playwright.config.ts` boots its own three `webServer` processes. Add a
**target-external-stack** mode (env-driven): when `PLAYWRIGHT_TARGET_URL` (+ optional
`PLAYWRIGHT_TOKEN`) is set, skip `webServer` and point `baseURL` at the scenario ingress. Drives
the login flow and sub-path SPA routing against the real proxied stack — catching client-side
proxy/auth bugs the API contract can't.

### 7.3 Contract module (escape hatch)

`assertions/contract.py` — a lean smoke set (health, one CRUD round-trip, auth reject/accept,
sub-path asset load, WS connect). Not the default, but `--quick` swaps the full engines for the
contract when you want a fast sweep across many arch/DB combos.

## 8. Manual-tester UX

`poe scenario up <name>` brings the stack up, seeds data (if the scenario asks), and prints a
summary block:

```
Scenario:  postgres-auth-nginx-subpath   [running]
URL:       http://localhost:48213/spoolman/
API token: Bearer sk_test_...             (SPOOLMAN_API_TOKEN)
DB:        postgres (project spoolman-scn-postgres-...-a1b2)
Seed:      12 filaments, 30 spools, 4 vendors
Stop:      poe scenario down postgres-auth-nginx-subpath
```

This is the "reproduce a user's bug report / hand to a tester" path — the identical stack the
automation asserts against, so a manual repro and an automated failure are the same environment.

## 9. Data seeding

`seed/sample.py` posts a small, deterministic dataset (vendors, filaments, spools) through the
public API after the stack is healthy. Scenarios choose `seed=empty` (assertion suites create
their own data) or `seed=sample` (manual-friendly). Seeding through the API (not DB inserts)
keeps it backend-agnostic and also exercises the write path under the scenario's auth+proxy.

## 10. Arch / QEMU handling

- Requires buildx + QEMU/binfmt (buildx already installed on this machine per prior setup).
- Arm images built per-arch via buildx `--platform`, cached and reused across scenarios.
- Arch scenarios run the **full** engines (approved), so a single armv7 run is minutes-long even
  on a fast box; the scheduler's per-scenario weighting prevents emulated stacks from starving
  native ones. `--quick` remains available for a contract-only arch sweep.

## 11. CI relationship

Local-only for now. No workflow ships. The catalog and assertion invocations are kept free of
local-machine assumptions (paths, engine names via `SPOOLMAN_CONTAINER_ENGINE`) so a future
nightly / `workflow_dispatch` job can import the catalog and run a chosen subset without
refactoring.

## 12. Testing the harness itself

- Unit-test `catalog.py` expansion logic (cross-product, meaningless-combo skipping, tag
  filtering) with plain pytest — no Docker.
- Unit-test port allocation and compose-project naming for uniqueness.
- One fast end-to-end self-check: `sqlite-bare` up → contract → down in CI-free local pytest,
  guarded to skip when Docker is unavailable.

## 13. Rollout phases

1. **Skeleton + seams** — `tests_scenarios/` scaffold, CLI verbs, the two assertion seams
   (integration `conftest` env-driven URL/token; Playwright external-target mode) with their
   defaults unchanged so existing suites/CI are unaffected.
2. **Runner + `sqlite-bare`** — lifecycle (dynamic ports, unique project, wait-healthy,
   teardown), single no-proxy scenario green end-to-end with the full integration suite.
3. **Auth axis** — `token` then `users` (login flow), integration + Playwright through auth.
4. **Proxy axis** — nginx (sub-path/root/forwarded), then traefik, then Caddy fixtures.
5. **Parallel scheduler** — worker pool, weights, `test-all`, `ps`/`down --all`.
6. **Arch axis** — armv7/arm64 under QEMU, full engines, build caching.
7. **Manual UX + seeding** — `up` summary block, `seed/sample.py`.
8. **Docs** — `tests_scenarios/README.md`, and a memory note on the local run recipe.

## 14. Risks & open questions

- **QEMU cost:** full suite + Playwright on armv7 is genuinely slow; mitigated by parallelism,
  weighting, and build caching, but a full `--arch all --db all` sweep is a "leave it running"
  job, not an inner-loop one. Accepted.
- **Playwright + emulated arch:** running a browser against a QEMU-emulated backend is fine
  (browser runs native, only the server is emulated) — confirm no fixture assumes a co-located
  server.
- **Proxy TLS variants:** self-signed certs for the TLS sub-variants need the assertion clients
  to trust them (env-injected CA / `verify=False` in test clients only). Scope TLS as a
  sub-variant, not core, to keep phase 4 tractable.
- **Compose v1 longevity:** the driver depends on v1 semantics; if the machine later gains v2,
  the driver should detect and prefer whichever `docker[-\ ]compose` is present.
