# Local deployment-scenario harness

A local runner that brings up **realistic Spoolman deployments** — crossing database
backend, auth mode, reverse proxy, and CPU architecture — and asserts against each one
with the project's existing test suites, in parallel. Any scenario can also be left
running for manual poking or handed to a tester. Automation and manual QA share one
scenario definition: the thing you click through is the thing the harness gates on.

Unlike `tests_integration/` (one fixed stack) or `tests_deployment/` (published release
artifacts), this harness composes **combinations** of deployment axes on demand, using
`docker-compose` directly rather than a workflow. It is **local-only** — no CI workflow
runs it (yet).

## CLI

Everything goes through `poe scenario <verb>` (`python -m tests_scenarios` under the
hood).

| Verb | Flags | What it does |
|---|---|---|
| `list` | — | Print every CORE scenario with its axis values and tags |
| `up <name>` | — | Bring a scenario up, wait for health, provision auth, seed data if configured, print a summary, and leave it running |
| `down [name]` | `--all` | Tear down one registered scenario, or every registered scenario |
| `test <name>` | `--keep` | Bring a scenario up, run contract + integration + e2e against it, tear down (unless `--keep`) |
| `test-all` | `--tags` `--db` `--auth` `--proxy` `--arch` `-j/--jobs` `--full`/`--quick` | Run every CORE scenario matching the filters, in parallel, print a pass/fail table |
| `ps` | — | List currently-registered (i.e. `up`'d) running scenarios |
| `logs <name>` | — | Stream `docker-compose logs -f` for a running scenario |

`test-all` filters (each accepts a comma-separated list; an axis with no flag keeps every
scenario on that axis):

- `--tags core,auth,proxy,arch` — keep scenarios with *any* of the listed tags
- `--db sqlite,postgres,mariadb,cockroachdb`
- `--auth none,token,users`
- `--proxy none,nginx,traefik,caddy`
- `--arch amd64,arm64,armv7`
- `-j/--jobs N` — concurrency budget (default: `os.cpu_count()`)
- `--full` (default) — contract + integration + Playwright e2e; `--quick` — contract only

### Examples

```bash
poe scenario list

poe scenario up sqlite-bare
poe scenario up postgres-auth-nginx-subpath
poe scenario ps
poe scenario logs postgres-auth-nginx-subpath
poe scenario down postgres-auth-nginx-subpath
poe scenario down --all

poe scenario test mariadb-traefik-root
poe scenario test mariadb-traefik-root --keep      # leave it up for inspection after the run

poe scenario test-all                               # every CORE scenario, full engines
poe scenario test-all --quick                        # contract only — fast sanity sweep
poe scenario test-all --db postgres,mariadb --auth token
poe scenario test-all --tags proxy -j 4
poe scenario test-all --arch armv7                   # slow: builds the armv7 image under QEMU
```

## Axes & the 5 CORE scenarios

Each `Scenario` is a point in five axes (`tests_scenarios/catalog.py`):

| Axis | Values |
|---|---|
| `db` | `sqlite` · `postgres` · `mariadb` · `cockroachdb` |
| `auth` | `none` · `token` (static `SPOOLMAN_API_TOKEN`) · `users` (per-user login) |
| `proxy` | `none` · `nginx` · `traefik` · `caddy` |
| `arch` | `amd64` · `arm64` · `armv7` (server image built/run under that platform) |
| `seed` | bool — `up` posts a small sample dataset through the API so a manual tester doesn't start from an empty DB (not a `test-all` filter; it only affects `up`) |

`CORE` (`tests_scenarios/catalog.py`) is the curated set every CLI verb draws from:

| Scenario | Axes | Proves |
|---|---|---|
| `sqlite-bare` | sqlite, no auth, no proxy | The baseline deployment always works |
| `postgres-auth-nginx-subpath` | postgres, token auth, nginx, sub-path `/spoolman`, seeded | The realistic self-hosted shape: real DB + static-token auth + proxy sub-path, with sample data left behind |
| `mariadb-traefik-root` | mariadb, no auth, traefik, root path | A different DB/proxy pairing, fronted at root instead of a sub-path |
| `cockroach-users-caddy-subpath` | cockroachdb, per-user login auth, caddy, sub-path `/spoolman` | The login-flow (not static-token) auth path, on another DB/proxy combo |
| `armv7-sqlite` | sqlite, armv7 (QEMU) | The server image actually builds and serves under a foreign arch — not just a health-check smoke test |

`catalog.expand()` can cross-product the axes into a larger combinatorial set for future
use, but it is not wired into the CLI today — every verb above operates on `CORE`.

## How assertions work

Every scenario is asserted against with up to three engines, run in this order:

1. **Contract** (`assertions/contract.py`) — lean and always runs: health check, a
   reject-without-token check if the scenario has auth, and one vendor CRUD round-trip.
2. **Integration** (`assertions/integration.py`) — the full existing suite, via
   `uv run pytest tests_integration/tests -q`, run from the host against the live stack.
   It reaches into `tests_integration/tests/conftest.py`'s seam: `SPOOLMAN_TEST_URL` points
   the suite at the scenario's URL, `DB_TYPE` picks the right `get_db_type()` branch, and
   `SPOOLMAN_TEST_TOKEN` / `SPOOLMAN_TEST_LOGIN` (`user:pass`) get the suite authenticated
   the way the scenario requires (`install_auth()` wraps `httpx.get/post/...` module-wide).
3. **E2E** (`assertions/e2e.py`) — Playwright's *external* mode, via `npx playwright test`
   from `client/`. Setting `PLAYWRIGHT_TARGET_URL` makes `client/playwright.config.ts`
   skip booting its local webServer trio entirely and run only `e2e/external.spec.ts`,
   single worker, against the running stack; `PLAYWRIGHT_TARGET_BASE` carries the
   sub-path (appended by the spec itself) and `PLAYWRIGHT_TOKEN` carries the bearer token.

`test-all --quick` (and `_run_scenario(..., quick=True)`) runs **contract only**, skipping
integration and e2e — a fast sanity sweep instead of the full ~3-engine run. Plain
`test-all` / `--full` runs all three.

## Machine prerequisites

- **Docker + `docker-compose` v1** — the harness shells out to `docker-compose` (the
  hyphenated v1 binary), **not** `docker compose` v2. Set `SPOOLMAN_CONTAINER_ENGINE` to
  override the engine (default `docker`; anything else runs `<engine> compose` instead of
  `<engine>-compose`).
- **A prebuilt client + the `spoolman:test` image.** The harness never builds these itself
  (`Arch.AMD64` always reuses the standing `spoolman:test` tag):
  ```bash
  cd client && npm ci && echo "VITE_APIURL=/api/v1" > .env.production && npm run build
  cd ..
  docker build -t spoolman:test .
  ```
- **`buildx` + QEMU/binfmt for arch scenarios** (`arm64`/`armv7`). `runner.ensure_image`
  handles this itself: it registers QEMU emulation (`docker run --privileged --rm
  tonistiigi/binfmt --install all`, idempotent) and runs `docker buildx build --platform
  <p> --load -t spoolman:scn-<arch> .` the first time an arch is needed, caching the tag
  for later runs. Building and running under QEMU is **slow** (armv7 in particular —
  expect on the order of ten minutes for a cold build).

## Manual-tester flow

```bash
poe scenario up postgres-auth-nginx-subpath
```

prints a summary and leaves the stack running:

```
============================================================
Scenario:  postgres-auth-nginx-subpath   [running]
URL:       http://localhost:<port>/spoolman/
API token: Bearer sk_scenario_local_admin
DB:        postgres (project spoolman-scn-postgres-auth-nginx-subpath-<suffix>)
Seeded:    1 vendors, 2 filaments, 3 spools
Stop:      poe scenario down postgres-auth-nginx-subpath
============================================================
```

(A `users`-auth scenario prints a `Login: tester:tester-pass (POST /auth/login)` line
instead of an API token.) From there:

- `poe scenario ps` — list what's currently up, with URLs
- `poe scenario logs <name>` — tail `docker-compose logs -f` for one stack
- `poe scenario down <name>` — stop and remove that one stack (compose `down -v`, temp
  compose/proxy-config files cleaned up)
- `poe scenario down --all` — stop everything currently registered

Running scenarios are tracked in `tests_scenarios/.state/running.json` (gitignored).

## Running the harness's own tests

The harness has its own pytest suite under `tests_scenarios/tests/`. One test —
`test_arch_scenario.py` — is marked `slow` because it performs a real armv7 image build
under QEMU (the same cold build described above). **A plain `pytest tests_scenarios/`
will run it.** For the fast sweep, exclude `slow` explicitly:

```bash
uv run pytest tests_scenarios/ -m "not slow"    # fast sweep: everything except the armv7 build
uv run pytest tests_scenarios/                  # full: includes the ~10-minute QEMU build
uv run pytest tests_scenarios/ -m slow          # just the armv7 self-test
```

Tests that need Docker (`test_smoke_sqlite.py`, `test_auth_scenario.py`,
`test_proxy_scenarios.py`, `test_users_scenario.py`, `test_arch_scenario.py`) each
`skipif` themselves when `docker` isn't on `PATH`, so the no-docker unit tests
(`test_cli.py`, `test_catalog.py`, `test_naming.py`, `test_scheduler.py`, and the env-builder
unit tests in `test_integration_engine.py`/`test_e2e_engine.py`) still run on a machine
without Docker.

## Reverse-proxy note

Spoolman is base-path-aware: it serves everything under `SPOOLMAN_BASE_PATH` and expects
requests to arrive with that prefix intact. So the nginx/traefik/caddy overlays in
`tests_scenarios/proxies/` pass the sub-path straight through to `spoolman:8000` — **no
prefix stripping** — for both root and sub-path scenarios. `wait_healthy` and the
assertion engines hit the health/API endpoints *through* the proxy, at the scenario's
real sub-path, so a proxy config that stripped the prefix would show up as a 404 rather
than silently passing.
