# Local Deployment-Scenario Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a bespoke Python CLI (`poe scenario`) that brings up realistic Spoolman
deployment scenarios (DB × auth × reverse-proxy × arch), runs the full existing
`tests_integration` suite + Playwright e2e against each, schedules them in parallel, and can
leave any scenario standing for manual use.

**Architecture:** A new `tests_scenarios/` package owns scenario definitions (a `Scenario`
dataclass + a curated core catalog with opt-in expansion) and lifecycle (dynamic ports, unique
compose project per scenario, wait-healthy, teardown), reusing the existing
`tests_integration/docker-compose-<db>.yml` files plus a rendered proxy overlay. The existing
assertion suites are made *targetable* by two small, backward-compatible seams: the integration
`conftest.py` learns to read its base URL and an auth token from env; Playwright learns a
target-external-stack mode. The CLI then invokes those suites as subprocesses per scenario.

**Tech Stack:** Python 3.12 (stdlib `argparse`, `asyncio`, `subprocess`, `socket`), `httpx`
(already a dep), `docker` + `docker-compose` v1 (v2 is NOT available on this machine),
`buildx` + QEMU/binfmt for arch scenarios, Playwright (`@playwright/test`, already wired),
`poethepoet` task runner, `pytest` + `pytest-asyncio` for harness self-tests.

## Global Constraints

- **No `docker compose` (v2) — only `docker-compose` (v1).** All orchestration shells out to
  `docker-compose` (hyphen). Respect `SPOOLMAN_CONTAINER_ENGINE` (default `docker`) as
  `tests_integration/run.py` already does.
- **The server image needs a prebuilt client.** Build order for any image build:
  `cd client && npm ci && echo "VITE_APIURL=/api/v1" > .env.production && npm run build`, then
  `docker build`. The Dockerfile COPYs `client/dist`; it does not build it.
- **Seams must default to today's behavior.** `tests_integration/conftest.py` and
  `client/playwright.config.ts` changes must be no-ops unless the new env vars are set, so the
  existing `poe itest` and `npm run test:e2e` and CI paths are unaffected.
- **Auth model:** both credentials ride `Authorization: Bearer <token>`; websockets pass
  `?token=<token>`. Static token = `SPOOLMAN_API_TOKEN` (admin). User accounts need
  `SPOOLMAN_AUTH_SECRET` and a `POST /auth/login`. Auth is enforced only when at least one is set.
- **Base path:** sub-path deploys set `SPOOLMAN_BASE_PATH` (no leading/trailing slash, e.g.
  `spoolman`); the client build stays `VITE_APIURL=/api/v1`.
- **Ruff `select = ["ALL"]`** repo-wide; `tests*/*` per-file-ignores already relax `S101`,
  `PLR2004`, `ANN201`, `D103`, etc. New harness code under `tests_scenarios/` inherits those.
- **Local-only:** no CI workflow ships. Keep `tests_scenarios/catalog.py` free of
  local-only assumptions (absolute paths, hard-coded engine) so a future job can import it.

---

## File Structure

```
tests_scenarios/
  __init__.py
  __main__.py             # CLI: argparse dispatch to commands
  catalog.py              # Scenario dataclass, DB/Auth/Proxy/Arch enums, CORE list, expand()
  naming.py               # free_port(), project_name()  (pure, unit-tested, no docker)
  runner.py               # bring_up(), wait_healthy(), tear_down(), ScenarioStack
  compose.py              # render_overlay() → temp compose file combining db base + proxy
  scheduler.py            # run_many() async worker pool with per-scenario weights
  seed.py                 # seed_sample() posts a deterministic dataset via the API
  assertions/
    __init__.py
    contract.py           # lean smoke checks (health, CRUD, auth, sub-path, WS)
    integration.py        # invoke tests_integration suite as a subprocess vs a stack
    e2e.py                # invoke Playwright target-external mode vs a stack
  proxies/
    nginx/subpath.conf.tmpl  nginx/root.conf.tmpl
    traefik/dynamic.yml.tmpl
    caddy/Caddyfile.tmpl
  compose/
    proxy.nginx.yml.tmpl  proxy.traefik.yml.tmpl  proxy.caddy.yml.tmpl
  tests/
    __init__.py
    test_naming.py        # port + project-name uniqueness (no docker)
    test_catalog.py       # dataclass resolution, expand() cross-product, filters
    test_smoke_sqlite.py  # docker-guarded end-to-end: sqlite-bare up→contract→down
  README.md

# Modified existing files:
tests_integration/tests/conftest.py   # env-driven URL + token injection seam
client/playwright.config.ts           # target-external-stack mode
client/e2e/external.spec.ts           # (new) journey spec that runs only in external mode
pyproject.toml                        # [tool.poe.tasks.scenario]
```

---

## Phase 1 — Assertion seams (make the existing suites targetable)

### Task 1: Env-drive the integration suite's URL and inject auth

**Files:**
- Modify: `tests_integration/tests/conftest.py:14-16` (URL) and add a session-start auth hook
- Test: `tests/test_scenario_conftest_seam.py` (new, host-side unit test — no docker)

**Interfaces:**
- Produces (consumed by Task 7 / `assertions/integration.py`): the suite honors env vars
  `SPOOLMAN_TEST_URL` (base URL, default `http://spoolman:$SPOOLMAN_PORT`),
  `SPOOLMAN_TEST_TOKEN` (bearer token, optional), and
  `SPOOLMAN_TEST_LOGIN` (`user:pass`, optional — logs in to obtain a token).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scenario_conftest_seam.py
"""The integration conftest must be env-drivable so the scenario harness can point it
at any ingress URL and inject an auth token, without changing any test call sites."""
import importlib
import httpx

CONFTEST = "tests_integration.tests.conftest"


def test_url_defaults_to_internal_compose_host(monkeypatch):
    monkeypatch.delenv("SPOOLMAN_TEST_URL", raising=False)
    monkeypatch.setenv("SPOOLMAN_PORT", "8000")
    mod = importlib.reload(importlib.import_module(CONFTEST))
    assert mod.URL == "http://spoolman:8000"


def test_url_overridden_by_env(monkeypatch):
    monkeypatch.setenv("SPOOLMAN_TEST_URL", "http://localhost:48213/spoolman")
    mod = importlib.reload(importlib.import_module(CONFTEST))
    assert mod.URL == "http://localhost:48213/spoolman"


def test_token_injected_as_bearer_header(monkeypatch):
    monkeypatch.setenv("SPOOLMAN_TEST_TOKEN", "sk_test_abc")
    mod = importlib.reload(importlib.import_module(CONFTEST))
    mod.install_auth()  # idempotent; installs the httpx monkeypatch
    captured = {}

    class DummyResp:
        def raise_for_status(self): ...

    def fake_request(method, url, **kwargs):
        captured["headers"] = kwargs.get("headers") or {}
        return DummyResp()

    monkeypatch.setattr(httpx, "_orig_request_for_test", fake_request, raising=False)
    # After install_auth, httpx.get must carry the bearer header.
    monkeypatch.setattr(mod._httpx_real, "request", fake_request)
    httpx.get("http://x/api/v1/health")
    assert captured["headers"]["Authorization"] == "Bearer sk_test_abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scenario_conftest_seam.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'install_auth'`.

- [ ] **Step 3: Write minimal implementation**

Replace `conftest.py:16` and add an auth-install helper + session hook. Keep the default
identical to today so `poe itest` is unaffected.

```python
# tests_integration/tests/conftest.py  (top of file, replacing the URL line)
import httpx

_httpx_real = httpx  # handle used by the monkeypatch + tests

URL = os.environ.get(
    "SPOOLMAN_TEST_URL",
    "http://spoolman:" + os.environ.get("SPOOLMAN_PORT", "8000"),
).rstrip("/")

_AUTH_INSTALLED = False


def _resolve_token() -> str | None:
    token = os.environ.get("SPOOLMAN_TEST_TOKEN")
    if token:
        return token
    login = os.environ.get("SPOOLMAN_TEST_LOGIN")
    if login and ":" in login:
        user, _, pw = login.partition(":")
        resp = httpx.post(f"{URL}/auth/login", json={"username": user, "password": pw}, timeout=10)
        resp.raise_for_status()
        return resp.json()["token"]
    return None


def install_auth() -> None:
    """Monkeypatch httpx module-level request funcs to add the bearer header. No-op when no token.

    The integration tests call ``httpx.get/post/...`` directly, so wrapping the module-level
    functions injects auth into every call site without editing any test file.
    """
    global _AUTH_INSTALLED  # noqa: PLW0603
    if _AUTH_INSTALLED:
        return
    token = _resolve_token()
    if not token:
        return
    header = {"Authorization": f"Bearer {token}"}
    for name in ("get", "post", "put", "patch", "delete", "request"):
        original = getattr(httpx, name)

        def wrapper(*args, __orig=original, **kwargs):  # noqa: ANN002, ANN003
            headers = {**header, **(kwargs.pop("headers", None) or {})}
            return __orig(*args, headers=headers, **kwargs)

        setattr(httpx, name, wrapper)
    _AUTH_INSTALLED = True


def ws_url(path: str) -> str:
    """Build a websocket URL, appending ?token= when an auth token is configured."""
    base = URL.replace("http://", "ws://").replace("https://", "wss://") + path
    token = os.environ.get("SPOOLMAN_TEST_TOKEN")
    return f"{base}?token={token}" if token else base
```

Then call `install_auth()` from the existing `pytest_sessionstart` **before** the wait loop, and
have the wait loop hit `f"{URL}/api/v1/health"` (unauthenticated, always 200) instead of `URL`:

```python
def pytest_sessionstart(session):  # noqa: ARG001, ANN001
    install_auth()
    start_time = time.time()
    while True:
        try:
            response = httpx.get(f"{URL}/api/v1/health", timeout=1)
            response.raise_for_status()
        except httpx.HTTPError:
            if time.time() - start_time > TIMEOUT:
                raise
            time.sleep(0.5)
        else:
            break
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scenario_conftest_seam.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Regression-check the default path still works**

Run: `uv run ruff check tests_integration/tests/conftest.py`
Expected: no new violations. (Confirms the seam didn't break lint; the full `poe itest` default
path is exercised later by Task 5's sqlite-bare run.)

- [ ] **Step 6: Commit**

```bash
git add tests_integration/tests/conftest.py tests/test_scenario_conftest_seam.py
git commit -m "test(integration): env-drive base URL + inject bearer token in conftest"
```

---

### Task 2: Playwright target-external-stack mode

**Files:**
- Modify: `client/playwright.config.ts`
- Create: `client/e2e/external.spec.ts`
- Test: manual verification command in Step 4 (Playwright config is validated by running it)

**Interfaces:**
- Produces (consumed by Task 9 / `assertions/e2e.py`): when `PLAYWRIGHT_TARGET_URL` is set,
  Playwright skips its `webServer` block, sets `use.baseURL` to that URL, runs **only**
  `e2e/external.spec.ts`, and exposes `PLAYWRIGHT_TARGET_BASE` (the sub-path, default `""`) and
  `PLAYWRIGHT_TOKEN` (optional) to the spec via `process.env`.

- [ ] **Step 1: Write the failing test (the external journey spec)**

```ts
// client/e2e/external.spec.ts
// Runs ONLY in target-external mode (PLAYWRIGHT_TARGET_URL set). Drives the real
// scenario stack (proxy + auth + DB) through the browser: load the SPA at its base
// path and confirm the app boots and can read the API.
import { expect, test } from "@playwright/test";

const BASE = process.env.PLAYWRIGHT_TARGET_BASE ?? "";

test("SPA boots against the external scenario stack", async ({ page }) => {
  await page.goto(`${BASE}/`);
  // config.js must have injected the base path and the app shell must mount.
  await expect(page.locator("#root")).toBeVisible();
  await expect(page).toHaveTitle(/Spoolman/i);
});
```

- [ ] **Step 2: Run it to verify it fails (no external mode yet)**

Run:
```bash
cd client && PLAYWRIGHT_TARGET_URL=http://127.0.0.1:1/ npx playwright test external.spec.ts --list
```
Expected: FAIL/empty — the spec is picked up by the *default* config which still tries to boot
`webServer`, so `--list` either errors on server boot or the external spec isn't isolated.

- [ ] **Step 3: Implement the external mode in the config**

Wrap the export so external mode short-circuits the webServer and narrows the test set:

```ts
// client/playwright.config.ts  (add near the top, after imports)
const targetUrl = process.env.PLAYWRIGHT_TARGET_URL;

// ... keep existing const definitions ...

export default defineConfig(
  targetUrl
    ? {
        testDir: "./e2e",
        testMatch: /external\.spec\.ts$/,
        fullyParallel: false,
        workers: 1,
        reporter: [["list"]],
        timeout: 60_000,
        expect: { timeout: 15_000 },
        use: {
          baseURL: targetUrl.replace(/\/$/, ""),
          trace: "on-first-retry",
          launchOptions,
          extraHTTPHeaders: process.env.PLAYWRIGHT_TOKEN
            ? { Authorization: `Bearer ${process.env.PLAYWRIGHT_TOKEN}` }
            : {},
        },
        projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
      }
    : {
        /* existing config object, unchanged */
      },
);
```

Move the current config object verbatim into the `else` branch (the object currently passed to
`defineConfig`). `launchOptions` and `devices` are already in scope.

- [ ] **Step 4: Run to verify external mode is isolated and default mode is intact**

Run (external — lists exactly the external spec, no webServer boot):
```bash
cd client && PLAYWRIGHT_TARGET_URL=http://127.0.0.1:30099 npx playwright test --list
```
Expected: lists only `external.spec.ts`.

Run (default — unchanged behavior):
```bash
cd client && npx playwright test --list
```
Expected: lists the existing specs (not `external.spec.ts`, since default `testDir` still
includes it — confirm by adding `testIgnore: /external\.spec\.ts$/` to the else-branch config).

- [ ] **Step 5: Commit**

```bash
git add client/playwright.config.ts client/e2e/external.spec.ts
git commit -m "test(e2e): add Playwright target-external-stack mode for scenario harness"
```

---

## Phase 2 — Scenario model + catalog

### Task 3: `Scenario` dataclass, enums, core catalog, and `expand()`

**Files:**
- Create: `tests_scenarios/__init__.py`, `tests_scenarios/catalog.py`
- Test: `tests_scenarios/tests/__init__.py`, `tests_scenarios/tests/test_catalog.py`

**Interfaces:**
- Produces (consumed by runner, scheduler, CLI):
  - `class Db(StrEnum)`: `SQLITE, POSTGRES, MARIADB, COCKROACH`
  - `class Auth(StrEnum)`: `NONE, TOKEN, USERS`
  - `class Proxy(StrEnum)`: `NONE, NGINX, TRAEFIK, CADDY`
  - `class Arch(StrEnum)`: `AMD64, ARM64, ARMV7`
  - `@dataclass(frozen=True) class Scenario` with fields `name: str`, `db: Db`,
    `auth: Auth = Auth.NONE`, `proxy: Proxy = Proxy.NONE`, `subpath: str = ""`,
    `arch: Arch = Arch.AMD64`, `seed: bool = False`, `tags: tuple[str, ...] = ()`,
    and methods `env() -> dict[str, str]`, `weight() -> int`.
  - `CORE: list[Scenario]` — the five curated scenarios from the spec §5.1.
  - `expand(*, tags, dbs, auths, proxies, arches) -> list[Scenario]` — filter/cross-product.

- [ ] **Step 1: Write the failing test**

```python
# tests_scenarios/tests/test_catalog.py
from tests_scenarios.catalog import CORE, Arch, Auth, Db, Proxy, Scenario, expand


def test_core_covers_every_db_auth_proxy_and_armv7():
    dbs = {s.db for s in CORE}
    assert dbs == {Db.SQLITE, Db.POSTGRES, Db.MARIADB, Db.COCKROACH}
    assert {s.auth for s in CORE} >= {Auth.NONE, Auth.TOKEN, Auth.USERS}
    assert {s.proxy for s in CORE} >= {Proxy.NGINX, Proxy.TRAEFIK, Proxy.CADDY}
    assert any(s.arch is Arch.ARMV7 for s in CORE)


def test_token_scenario_sets_api_token_env():
    s = Scenario(name="t", db=Db.SQLITE, auth=Auth.TOKEN)
    env = s.env()
    assert env["SPOOLMAN_API_TOKEN"]  # non-empty


def test_subpath_scenario_sets_base_path():
    s = Scenario(name="t", db=Db.SQLITE, proxy=Proxy.NGINX, subpath="spoolman")
    assert s.env()["SPOOLMAN_BASE_PATH"] == "spoolman"


def test_armv7_weighs_more_than_amd64():
    light = Scenario(name="a", db=Db.SQLITE, arch=Arch.AMD64)
    heavy = Scenario(name="b", db=Db.SQLITE, arch=Arch.ARMV7)
    assert heavy.weight() > light.weight()


def test_expand_filters_and_crosses():
    out = expand(dbs=[Db.SQLITE, Db.POSTGRES], proxies=[Proxy.NGINX], arches=[Arch.AMD64])
    assert {s.db for s in out} == {Db.SQLITE, Db.POSTGRES}
    assert all(s.proxy is Proxy.NGINX for s in out)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests_scenarios/tests/test_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: tests_scenarios.catalog`.

- [ ] **Step 3: Implement `catalog.py`**

```python
# tests_scenarios/catalog.py
"""Scenario definitions: the axes, the curated core set, and expansion."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# A fixed, non-secret token is fine — these stacks are throwaway and never exposed.
_STATIC_TOKEN = "sk_scenario_local_admin"  # noqa: S105
_USER = "tester"
_PASSWORD = "tester-pass"  # noqa: S105
_SECRET = "scenario-signing-secret"  # noqa: S105


class Db(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    MARIADB = "mariadb"
    COCKROACH = "cockroachdb"


class Auth(StrEnum):
    NONE = "none"
    TOKEN = "token"
    USERS = "users"


class Proxy(StrEnum):
    NONE = "none"
    NGINX = "nginx"
    TRAEFIK = "traefik"
    CADDY = "caddy"


class Arch(StrEnum):
    AMD64 = "amd64"
    ARM64 = "arm64"
    ARMV7 = "armv7"


_ARCH_WEIGHT = {Arch.AMD64: 1, Arch.ARM64: 4, Arch.ARMV7: 6}
_PLATFORM = {Arch.AMD64: "linux/amd64", Arch.ARM64: "linux/arm64", Arch.ARMV7: "linux/arm/v7"}


@dataclass(frozen=True)
class Scenario:
    name: str
    db: Db
    auth: Auth = Auth.NONE
    proxy: Proxy = Proxy.NONE
    subpath: str = ""
    arch: Arch = Arch.AMD64
    seed: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def platform(self) -> str:
        return _PLATFORM[self.arch]

    def weight(self) -> int:
        return _ARCH_WEIGHT[self.arch]

    def env(self) -> dict[str, str]:
        """Server-container env for this scenario."""
        env: dict[str, str] = {}
        if self.subpath:
            env["SPOOLMAN_BASE_PATH"] = self.subpath
        if self.auth is Auth.TOKEN:
            env["SPOOLMAN_API_TOKEN"] = _STATIC_TOKEN
        elif self.auth is Auth.USERS:
            env["SPOOLMAN_AUTH_SECRET"] = _SECRET
        return env

    def test_env(self) -> dict[str, str]:
        """Env the assertion suites need to target this scenario (URL is added by the runner)."""
        env: dict[str, str] = {}
        if self.auth is Auth.TOKEN:
            env["SPOOLMAN_TEST_TOKEN"] = _STATIC_TOKEN
        elif self.auth is Auth.USERS:
            env["SPOOLMAN_TEST_LOGIN"] = f"{_USER}:{_PASSWORD}"
        return env


CORE: list[Scenario] = [
    Scenario("sqlite-bare", Db.SQLITE, tags=("core",)),
    Scenario("postgres-auth-nginx-subpath", Db.POSTGRES, Auth.TOKEN, Proxy.NGINX,
             subpath="spoolman", seed=True, tags=("core", "auth", "proxy")),
    Scenario("mariadb-traefik-root", Db.MARIADB, Auth.NONE, Proxy.TRAEFIK, tags=("core", "proxy")),
    Scenario("cockroach-users-caddy-subpath", Db.COCKROACH, Auth.USERS, Proxy.CADDY,
             subpath="spoolman", tags=("core", "auth", "proxy")),
    Scenario("armv7-sqlite", Db.SQLITE, arch=Arch.ARMV7, tags=("core", "arch")),
]


def expand(*, tags=None, dbs=None, auths=None, proxies=None, arches=None) -> list[Scenario]:
    """Cross-product the requested axes; unspecified axes take a single sensible default."""
    dbs = list(dbs) if dbs else [Db.SQLITE]
    auths = list(auths) if auths else [Auth.NONE]
    proxies = list(proxies) if proxies else [Proxy.NONE]
    arches = list(arches) if arches else [Arch.AMD64]
    out: list[Scenario] = []
    for db in dbs:
        for auth in auths:
            for proxy in proxies:
                for arch in arches:
                    sub = "spoolman" if proxy is not Proxy.NONE else ""
                    name = f"{db}-{auth}-{proxy}-{arch}"
                    out.append(Scenario(name, db, auth, proxy, subpath=sub, arch=arch,
                                        tags=tuple(tags or ())))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests_scenarios/tests/test_catalog.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tests_scenarios/__init__.py tests_scenarios/catalog.py tests_scenarios/tests/
git commit -m "feat(scenarios): scenario dataclass, curated core catalog, and expand()"
```

---

## Phase 3 — Runner (lifecycle for a single scenario)

### Task 4: Pure helpers — free ports and unique project names

**Files:**
- Create: `tests_scenarios/naming.py`
- Test: `tests_scenarios/tests/test_naming.py`

**Interfaces:**
- Produces: `free_port() -> int` (an OS-assigned free TCP port), and
  `project_name(scenario_name: str) -> str` (unique, docker-safe compose project name).

- [ ] **Step 1: Write the failing test**

```python
# tests_scenarios/tests/test_naming.py
import re
from tests_scenarios.naming import free_port, project_name


def test_free_port_returns_distinct_usable_ports():
    a, b = free_port(), free_port()
    assert 1024 < a < 65536
    assert a != b


def test_project_name_is_docker_safe_and_unique():
    n1 = project_name("postgres-auth-nginx-subpath")
    n2 = project_name("postgres-auth-nginx-subpath")
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", n1)
    assert n1 != n2  # includes a random suffix
    assert n1.startswith("spoolman-scn-postgres-auth-nginx-subpath-")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests_scenarios/tests/test_naming.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `naming.py`**

```python
# tests_scenarios/naming.py
"""Pure, docker-free helpers: free ports and unique compose project names."""
from __future__ import annotations

import secrets
import socket


def free_port() -> int:
    """Ask the OS for an unused TCP port (bind :0, read it back, release)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def project_name(scenario_name: str) -> str:
    """A unique, docker-compose-safe project name so parallel stacks never collide."""
    suffix = secrets.token_hex(3)
    return f"spoolman-scn-{scenario_name}-{suffix}".lower()
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests_scenarios/tests/test_naming.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tests_scenarios/naming.py tests_scenarios/tests/test_naming.py
git commit -m "feat(scenarios): free_port + unique compose project-name helpers"
```

---

### Task 5: Runner brings up `sqlite-bare`, waits healthy, tears down

This task delivers the first fully working vertical slice: a real stack up + contract + down.
It folds in the minimal `compose.py` (proxy=none path only) and `assertions/contract.py`.

**Files:**
- Create: `tests_scenarios/compose.py`, `tests_scenarios/runner.py`,
  `tests_scenarios/assertions/__init__.py`, `tests_scenarios/assertions/contract.py`
- Test: `tests_scenarios/tests/test_smoke_sqlite.py` (docker-guarded)

**Interfaces:**
- `compose.render(scenario, *, host_port, project) -> Path` — writes a temp compose file that
  extends `tests_integration/docker-compose-<db>.yml` with the scenario's env + published port
  (proxy overlay added in Phase 5; for now proxy must be `NONE`).
- `runner.bring_up(scenario) -> ScenarioStack` where
  `ScenarioStack = namedtuple("ScenarioStack", "scenario project host_port url compose_file")`;
  `url` is `http://localhost:<host_port>` + (`/<subpath>` if set).
- `runner.wait_healthy(stack, timeout=180) -> None` — polls `<url>/api/v1/health`.
- `runner.tear_down(stack) -> None` — `docker-compose -p <project> down -v` and unlink temp file.
- `contract.run(stack) -> None` — raises `AssertionError` on any failed check.

- [ ] **Step 1: Write the failing test (docker-guarded end-to-end)**

```python
# tests_scenarios/tests/test_smoke_sqlite.py
import shutil
import pytest
from tests_scenarios.assertions import contract
from tests_scenarios.catalog import Scenario, Db
from tests_scenarios import runner

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def test_sqlite_bare_up_contract_down():
    scenario = Scenario("sqlite-bare-selftest", Db.SQLITE)
    stack = runner.bring_up(scenario)
    try:
        runner.wait_healthy(stack)
        contract.run(stack)  # health + one CRUD round-trip
    finally:
        runner.tear_down(stack)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests_scenarios/tests/test_smoke_sqlite.py -v`
Expected: FAIL — `ModuleNotFoundError: tests_scenarios.runner`.

- [ ] **Step 3: Implement `compose.render` (proxy=none)**

The existing `tests_integration/docker-compose-sqlite.yml` defines a `spoolman` service and a
`tester`. We reuse only its `spoolman` service by generating a compose file that `extends` it (or
inlines it) with our env + a published port. Read the base file first to match its service name
and image tag, then:

```python
# tests_scenarios/compose.py
"""Render a temporary docker-compose file for a scenario (v1 syntax)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from tests_scenarios.catalog import Proxy, Scenario

REPO = Path(__file__).resolve().parent.parent
BASE = REPO / "tests_integration"


def render(scenario: Scenario, *, host_port: int, project: str) -> Path:
    if scenario.proxy is not Proxy.NONE:
        raise NotImplementedError("proxy overlays land in Phase 5")
    base = yaml.safe_load((BASE / f"docker-compose-{scenario.db}.yml").read_text())
    services = base["services"]
    spoolman = services["spoolman"]
    spoolman.setdefault("environment", {})
    if isinstance(spoolman["environment"], list):  # normalize KEY=VAL list → dict
        spoolman["environment"] = dict(kv.split("=", 1) for kv in spoolman["environment"])
    spoolman["environment"].update(scenario.env())
    spoolman["ports"] = [f"{host_port}:8000"]
    # Drop the internal tester service — the scenario harness asserts from the host.
    services.pop("tester", None)
    out = {"services": {"spoolman": spoolman}}
    # Keep any db service the base defined (postgres/mariadb/cockroachdb); sqlite has none.
    for name, svc in services.items():
        if name != "spoolman":
            out["services"][name] = svc
    fd = tempfile.NamedTemporaryFile(
        prefix=f"{project}-", suffix=".yml", delete=False, mode="w", dir=tempfile.gettempdir())
    fd.write(yaml.safe_dump(out))
    fd.close()
    return Path(fd.name)
```

> Implementer note: open `tests_integration/docker-compose-sqlite.yml` and
> `-postgres.yml` first; confirm the server service key is `spoolman` and that it listens on
> `8000` internally (`SPOOLMAN_PORT`). Adjust the `8000` and service key here to match reality.

- [ ] **Step 4: Implement `runner.py`**

```python
# tests_scenarios/runner.py
"""Lifecycle for a single scenario stack (docker-compose v1)."""
from __future__ import annotations

import os
import subprocess
import time
from collections import namedtuple
from pathlib import Path

import httpx

from tests_scenarios import compose
from tests_scenarios.catalog import Scenario
from tests_scenarios.naming import free_port, project_name

ENGINE = os.environ.get("SPOOLMAN_CONTAINER_ENGINE", "docker")
COMPOSE = [ENGINE + "-compose"] if ENGINE == "docker" else [ENGINE, "compose"]

ScenarioStack = namedtuple("ScenarioStack", "scenario project host_port url compose_file")


def _compose_cmd(project: str, compose_file: Path, *args: str) -> list[str]:
    return [*COMPOSE, "-p", project, "-f", str(compose_file), *args]


def bring_up(scenario: Scenario) -> ScenarioStack:
    host_port = free_port()
    project = project_name(scenario.name)
    compose_file = compose.render(scenario, host_port=host_port, project=project)
    url = f"http://localhost:{host_port}" + (f"/{scenario.subpath}" if scenario.subpath else "")
    stack = ScenarioStack(scenario, project, host_port, url, compose_file)
    subprocess.run(_compose_cmd(project, compose_file, "up", "-d"), check=True)
    return stack


def wait_healthy(stack: ScenarioStack, timeout: int = 180) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            r = httpx.get(f"{stack.url}/api/v1/health", timeout=2)
            if r.is_success:
                return
            last = f"{r.status_code} {r.text[:200]}"
        except httpx.HTTPError as e:
            last = str(e)
        time.sleep(1)
    raise TimeoutError(f"{stack.scenario.name} not healthy in {timeout}s: {last}")


def tear_down(stack: ScenarioStack) -> None:
    subprocess.run(_compose_cmd(stack.project, stack.compose_file, "down", "-v"), check=False)
    stack.compose_file.unlink(missing_ok=True)
```

- [ ] **Step 5: Implement `assertions/contract.py`**

```python
# tests_scenarios/assertions/contract.py
"""Lean deployment contract: health + one CRUD round-trip + (if auth) reject-without-token."""
from __future__ import annotations

import httpx

from tests_scenarios.catalog import Auth
from tests_scenarios.runner import ScenarioStack


def run(stack: ScenarioStack) -> None:
    tenv = stack.scenario.test_env()
    token = tenv.get("SPOOLMAN_TEST_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    httpx.get(f"{stack.url}/api/v1/health", timeout=10).raise_for_status()

    if stack.scenario.auth is Auth.TOKEN:
        anon = httpx.get(f"{stack.url}/api/v1/vendor", timeout=10)
        if anon.status_code not in (401, 403):
            raise AssertionError(f"auth not enforced: anon vendor list => {anon.status_code}")

    created = httpx.post(f"{stack.url}/api/v1/vendor", json={"name": "contract-vendor"},
                         headers=headers, timeout=10)
    created.raise_for_status()
    vid = created.json()["id"]
    got = httpx.get(f"{stack.url}/api/v1/vendor/{vid}", headers=headers, timeout=10)
    got.raise_for_status()
    if got.json()["name"] != "contract-vendor":
        raise AssertionError("CRUD round-trip mismatch")
    httpx.delete(f"{stack.url}/api/v1/vendor/{vid}", headers=headers, timeout=10).raise_for_status()
```

- [ ] **Step 6: Build the server image, then run the smoke test**

```bash
cd client && npm ci && echo "VITE_APIURL=/api/v1" > .env.production && npm run build && cd ..
docker build -t donkie/spoolman:test .   # tag the base compose files expect; confirm from the yml
uv run pytest tests_scenarios/tests/test_smoke_sqlite.py -v -s
```
Expected: PASS — the stack comes up, contract passes, teardown runs. If the image tag differs
from what `docker-compose-sqlite.yml` references, build that tag instead (read the file).

- [ ] **Step 7: Commit**

```bash
git add tests_scenarios/compose.py tests_scenarios/runner.py tests_scenarios/assertions/ \
        tests_scenarios/tests/test_smoke_sqlite.py
git commit -m "feat(scenarios): single-scenario runner + contract, sqlite-bare green"
```

---

## Phase 4 — CLI

### Task 6: `poe scenario` CLI (list / up / down / test / ps / logs)

**Files:**
- Create: `tests_scenarios/__main__.py`
- Modify: `pyproject.toml` (add `[tool.poe.tasks.scenario]`)
- Test: `tests_scenarios/tests/test_cli.py`

**Interfaces:**
- `poe scenario <cmd>` dispatches: `list`, `up NAME`, `down NAME|--all`, `test NAME [--keep]`,
  `ps`, `logs NAME`. Running stacks are tracked in a small JSON registry at
  `tests_scenarios/.state/running.json` (gitignored) so `down`/`ps`/`logs` work across processes.

- [ ] **Step 1: Write the failing test (CLI parses and lists the catalog without docker)**

```python
# tests_scenarios/tests/test_cli.py
from tests_scenarios.__main__ import build_parser, cmd_list


def test_list_prints_core_scenarios(capsys):
    cmd_list(build_parser().parse_args(["list"]))
    out = capsys.readouterr().out
    assert "sqlite-bare" in out
    assert "armv7-sqlite" in out


def test_parser_rejects_unknown_command():
    import pytest
    with pytest.raises(SystemExit):
        build_parser().parse_args(["frobnicate"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests_scenarios/tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError` / no `build_parser`.

- [ ] **Step 3: Implement `__main__.py`**

```python
# tests_scenarios/__main__.py
"""CLI for the local deployment-scenario harness."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tests_scenarios.catalog import CORE

STATE = Path(__file__).resolve().parent / ".state" / "running.json"


def _registry() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def _by_name(name: str):
    for s in CORE:
        if s.name == name:
            return s
    raise SystemExit(f"unknown scenario: {name} (see `poe scenario list`)")


def cmd_list(_args) -> None:
    for s in CORE:
        tags = ",".join(s.tags)
        print(f"{s.name:34} db={s.db:11} auth={s.auth:6} proxy={s.proxy:8} arch={s.arch:6} [{tags}]")


def cmd_up(args) -> None:
    from tests_scenarios import runner
    from tests_scenarios.seed import seed_sample
    stack = runner.bring_up(_by_name(args.name))
    runner.wait_healthy(stack)
    if stack.scenario.seed:
        seed_sample(stack)
    STATE.parent.mkdir(exist_ok=True)
    reg = _registry()
    reg[stack.scenario.name] = {"project": stack.project, "port": stack.host_port,
                                "url": stack.url, "compose_file": str(stack.compose_file)}
    STATE.write_text(json.dumps(reg, indent=2))
    _print_summary(stack)


def cmd_down(args) -> None:
    from tests_scenarios import runner
    from tests_scenarios.catalog import Scenario, Db
    reg = _registry()
    names = list(reg) if args.all else [args.name]
    for name in names:
        info = reg.get(name)
        if not info:
            continue
        stack = runner.ScenarioStack(Scenario(name, Db.SQLITE), info["project"], info["port"],
                                     info["url"], Path(info["compose_file"]))
        runner.tear_down(stack)
        reg.pop(name, None)
    STATE.write_text(json.dumps(reg, indent=2))


def cmd_test(args) -> None:
    from tests_scenarios import runner
    from tests_scenarios.assertions import contract, integration, e2e
    stack = runner.bring_up(_by_name(args.name))
    try:
        runner.wait_healthy(stack)
        contract.run(stack)
        integration.run(stack)
        e2e.run(stack)
    finally:
        if not args.keep:
            runner.tear_down(stack)


def cmd_ps(_args) -> None:
    for name, info in _registry().items():
        print(f"{name:34} {info['url']}  (project {info['project']})")


def cmd_logs(args) -> None:
    import subprocess
    from tests_scenarios import runner
    info = _registry().get(args.name) or _raise(args.name)
    subprocess.run([*runner.COMPOSE, "-p", info["project"], "-f", info["compose_file"], "logs",
                    "-f"], check=False)


def _raise(name: str):
    raise SystemExit(f"{name} is not running (see `poe scenario ps`)")


def _print_summary(stack) -> None:
    tenv = stack.scenario.test_env()
    print("\n" + "=" * 60)
    print(f"Scenario:  {stack.scenario.name}   [running]")
    print(f"URL:       {stack.url}/")
    if "SPOOLMAN_TEST_TOKEN" in tenv:
        print(f"API token: Bearer {tenv['SPOOLMAN_TEST_TOKEN']}")
    if "SPOOLMAN_TEST_LOGIN" in tenv:
        print(f"Login:     {tenv['SPOOLMAN_TEST_LOGIN']}  (POST /auth/login)")
    print(f"DB:        {stack.scenario.db} (project {stack.project})")
    print(f"Stop:      poe scenario down {stack.scenario.name}")
    print("=" * 60)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scenario")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    up = sub.add_parser("up"); up.add_argument("name"); up.set_defaults(func=cmd_up)
    dn = sub.add_parser("down"); dn.add_argument("name", nargs="?"); dn.add_argument("--all", action="store_true"); dn.set_defaults(func=cmd_down)
    ts = sub.add_parser("test"); ts.add_argument("name"); ts.add_argument("--keep", action="store_true"); ts.set_defaults(func=cmd_test)
    sub.add_parser("ps").set_defaults(func=cmd_ps)
    lg = sub.add_parser("logs"); lg.add_argument("name"); lg.set_defaults(func=cmd_logs)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Wire the poe task and gitignore state**

Add to `pyproject.toml` after `[tool.poe.tasks.itest]`:

```toml
[tool.poe.tasks.scenario]
cmd = "python -m tests_scenarios"
help = "Local deployment-scenario harness: list/up/down/test/ps/logs."
```

Append to `.gitignore`:

```
tests_scenarios/.state/
```

- [ ] **Step 5: Run tests + a real `list`**

Run: `uv run pytest tests_scenarios/tests/test_cli.py -v && uv run poe scenario list`
Expected: tests PASS; `list` prints the five core scenarios.

- [ ] **Step 6: Commit**

```bash
git add tests_scenarios/__main__.py tests_scenarios/tests/test_cli.py pyproject.toml .gitignore
git commit -m "feat(scenarios): poe scenario CLI (list/up/down/test/ps/logs)"
```

---

## Phase 5 — Assertion engines: integration suite + Playwright per scenario

### Task 7: `assertions/integration.py` — run the full suite from the host

**Files:**
- Create: `tests_scenarios/assertions/integration.py`
- Test: extend `tests_scenarios/tests/test_smoke_sqlite.py` with an `integration.run` call

**Interfaces:**
- `integration.run(stack, *, extra_pytest_args=()) -> None` — runs
  `uv run pytest tests_integration/tests` in a subprocess with `SPOOLMAN_TEST_URL=<stack.url>`
  plus the scenario's `test_env()`; raises `AssertionError` on non-zero exit.

- [ ] **Step 1: Write the failing test**

```python
# add to tests_scenarios/tests/test_smoke_sqlite.py
def test_sqlite_bare_full_integration_suite():
    from tests_scenarios.assertions import integration
    scenario = Scenario("sqlite-bare-itest", Db.SQLITE)
    stack = runner.bring_up(scenario)
    try:
        runner.wait_healthy(stack)
        integration.run(stack, extra_pytest_args=("-k", "vendor"))  # subset keeps the self-test fast
    finally:
        runner.tear_down(stack)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests_scenarios/tests/test_smoke_sqlite.py::test_sqlite_bare_full_integration_suite -v`
Expected: FAIL — no `integration` module.

- [ ] **Step 3: Implement**

```python
# tests_scenarios/assertions/integration.py
"""Run the existing tests_integration suite against a live scenario stack (from the host)."""
from __future__ import annotations

import os
import subprocess

from tests_scenarios.runner import REPO, ScenarioStack


def run(stack: ScenarioStack, *, extra_pytest_args: tuple[str, ...] = ()) -> None:
    env = {**os.environ, "SPOOLMAN_TEST_URL": stack.url, **stack.scenario.test_env()}
    cmd = ["uv", "run", "pytest", "tests_integration/tests", "-q", *extra_pytest_args]
    result = subprocess.run(cmd, cwd=REPO, env=env, check=False)
    if result.returncode != 0:
        raise AssertionError(f"integration suite failed for {stack.scenario.name} (exit {result.returncode})")
```

Add `REPO = Path(__file__).resolve().parent.parent.parent` export to `runner.py` (or import from
`compose.REPO`). Ensure `runner` exposes `REPO`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests_scenarios/tests/test_smoke_sqlite.py::test_sqlite_bare_full_integration_suite -v -s`
Expected: PASS — the vendor subset of the real integration suite runs green against the stack.

- [ ] **Step 5: Commit**

```bash
git add tests_scenarios/assertions/integration.py tests_scenarios/tests/test_smoke_sqlite.py tests_scenarios/runner.py
git commit -m "feat(scenarios): run full tests_integration suite against a scenario from the host"
```

---

### Task 8: `assertions/e2e.py` — drive Playwright against a scenario

**Files:**
- Create: `tests_scenarios/assertions/e2e.py`

**Interfaces:**
- `e2e.run(stack) -> None` — runs `npx playwright test` in `client/` with
  `PLAYWRIGHT_TARGET_URL=<origin>`, `PLAYWRIGHT_TARGET_BASE=/<subpath>`, and
  `PLAYWRIGHT_TOKEN` when the scenario is token-auth; raises on non-zero exit.

- [ ] **Step 1: Implement (no separate unit test — validated live in Task 10 core run)**

```python
# tests_scenarios/assertions/e2e.py
"""Drive Playwright's target-external mode against a live scenario stack."""
from __future__ import annotations

import os
import subprocess

from tests_scenarios.runner import REPO, ScenarioStack


def run(stack: ScenarioStack) -> None:
    origin = f"http://localhost:{stack.host_port}"
    base = f"/{stack.scenario.subpath}" if stack.scenario.subpath else ""
    env = {**os.environ, "PLAYWRIGHT_TARGET_URL": origin, "PLAYWRIGHT_TARGET_BASE": base}
    token = stack.scenario.test_env().get("SPOOLMAN_TEST_TOKEN")
    if token:
        env["PLAYWRIGHT_TOKEN"] = token
    result = subprocess.run(["npx", "playwright", "test"], cwd=REPO / "client", env=env, check=False)
    if result.returncode != 0:
        raise AssertionError(f"Playwright e2e failed for {stack.scenario.name} (exit {result.returncode})")
```

- [ ] **Step 2: Sanity-run against a live sqlite-bare stack**

```bash
uv run poe scenario up sqlite-bare
# in another shell, using the printed port:
cd client && PLAYWRIGHT_TARGET_URL=http://localhost:<port> PLAYWRIGHT_TARGET_BASE="" npx playwright test
uv run poe scenario down sqlite-bare
```
Expected: `external.spec.ts` passes against the running stack.

- [ ] **Step 3: Commit**

```bash
git add tests_scenarios/assertions/e2e.py
git commit -m "feat(scenarios): drive Playwright external mode against a scenario stack"
```

---

## Phase 6 — Auth axis (end-to-end)

### Task 9: `token` auth scenario green through all engines

**Files:**
- Test: `tests_scenarios/tests/test_auth_scenario.py` (docker-guarded)

**Interfaces:** consumes `Scenario(..., auth=Auth.TOKEN)`; verifies the contract's
reject-without-token check and that the integration suite passes *with* the injected token.

- [ ] **Step 1: Write the failing test**

```python
# tests_scenarios/tests/test_auth_scenario.py
import shutil
import pytest
from tests_scenarios import runner
from tests_scenarios.assertions import contract, integration
from tests_scenarios.catalog import Auth, Db, Scenario

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def test_token_auth_enforced_and_suite_passes_with_token():
    s = Scenario("sqlite-token-selftest", Db.SQLITE, auth=Auth.TOKEN)
    stack = runner.bring_up(s)
    try:
        runner.wait_healthy(stack)
        contract.run(stack)  # includes anon-rejected assertion
        integration.run(stack, extra_pytest_args=("-k", "vendor"))
    finally:
        runner.tear_down(stack)
```

- [ ] **Step 2: Run to verify it fails, then pass**

Run: `uv run pytest tests_scenarios/tests/test_auth_scenario.py -v -s`
Expected first run: it should actually PASS if Tasks 1/3/5/7 are correct (env + token injection
already wired). If the anon check fails, fix `contract.run` / `Scenario.env`. This task's value is
proving the token path end-to-end; no new production code beyond fixes.

- [ ] **Step 3: Commit**

```bash
git add tests_scenarios/tests/test_auth_scenario.py
git commit -m "test(scenarios): token-auth scenario enforced + suite passes with token"
```

---

### Task 10: `users` auth scenario (login flow)

**Files:**
- Modify: `tests_scenarios/runner.py` — after `wait_healthy`, if `auth is USERS`, create the user
  account so `POST /auth/login` works. (Confirm the user-creation endpoint from
  `spoolman/users.py` / the API before writing.)
- Test: `tests_scenarios/tests/test_users_scenario.py` (docker-guarded)

**Interfaces:** `runner.provision_users(stack) -> None` — idempotently creates the `tester` admin
account used by `SPOOLMAN_TEST_LOGIN`.

- [ ] **Step 1: Discover the user-creation contract**

Run: `grep -rn "auth/login\|def .*user\|create_user\|/user" spoolman/router/*.py spoolman/users.py`
Confirm the endpoint + payload to create an admin user and to log in. Write the test to that
contract. (Do not guess — read the router.)

- [ ] **Step 2: Write the failing test**

```python
# tests_scenarios/tests/test_users_scenario.py
import shutil
import pytest
from tests_scenarios import runner
from tests_scenarios.assertions import contract, integration
from tests_scenarios.catalog import Auth, Db, Scenario

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def test_users_login_flow_yields_working_token():
    s = Scenario("sqlite-users-selftest", Db.SQLITE, auth=Auth.USERS)
    stack = runner.bring_up(s)
    try:
        runner.wait_healthy(stack)
        runner.provision_users(stack)
        contract.run(stack)
        integration.run(stack, extra_pytest_args=("-k", "vendor"))
    finally:
        runner.tear_down(stack)
```

- [ ] **Step 3: Implement `provision_users` per the discovered contract, run, commit**

Run: `uv run pytest tests_scenarios/tests/test_users_scenario.py -v -s` → PASS.
```bash
git add tests_scenarios/runner.py tests_scenarios/tests/test_users_scenario.py
git commit -m "feat(scenarios): provision admin user for the login-flow auth scenario"
```

---

## Phase 7 — Proxy axis (nginx, traefik, caddy)

### Task 11: Proxy overlays + configs, wired into `compose.render`

**Files:**
- Create: `tests_scenarios/proxies/nginx/subpath.conf.tmpl`, `.../nginx/root.conf.tmpl`,
  `.../traefik/dynamic.yml.tmpl`, `.../caddy/Caddyfile.tmpl`
- Modify: `tests_scenarios/compose.py` — add the proxy sidecar + rewire the published port to the
  proxy, keep the server unpublished on the compose network.
- Test: `tests_scenarios/tests/test_proxy_scenarios.py` (docker-guarded, one per proxy)

**Interfaces:** `compose.render` now handles `Proxy.{NGINX,TRAEFIK,CADDY}`: the server port is
internal, a proxy service publishes `host_port:80` and forwards to `spoolman:8000` under the
scenario's sub-path (or root), setting `X-Forwarded-Proto/Host/Prefix`.

- [ ] **Step 1: Write the nginx sub-path config**

```nginx
# tests_scenarios/proxies/nginx/subpath.conf.tmpl   ({{SUBPATH}} substituted by compose.render)
server {
  listen 80;
  location = /{{SUBPATH}} { return 301 /{{SUBPATH}}/; }
  location /{{SUBPATH}}/ {
    proxy_pass http://spoolman:8000/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix /{{SUBPATH}};
    proxy_set_header Upgrade $http_upgrade;      # websockets
    proxy_set_header Connection "upgrade";
  }
}
```

Add `root.conf.tmpl` (same, `location /` → `proxy_pass http://spoolman:8000;`, no prefix), and the
traefik `dynamic.yml.tmpl` + `Caddyfile.tmpl` equivalents. For Caddy sub-path:

```
# tests_scenarios/proxies/caddy/Caddyfile.tmpl
:80 {
  handle_path /{{SUBPATH}}/* {
    reverse_proxy spoolman:8000
  }
  redir /{{SUBPATH}} /{{SUBPATH}}/ 308
}
```

- [ ] **Step 2: Write the failing test (one representative proxy first: nginx sub-path)**

```python
# tests_scenarios/tests/test_proxy_scenarios.py
import shutil
import httpx
import pytest
from tests_scenarios import runner
from tests_scenarios.assertions import contract
from tests_scenarios.catalog import Db, Proxy, Scenario

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def test_nginx_subpath_serves_api_and_spa():
    s = Scenario("sqlite-nginx-subpath-selftest", Db.SQLITE, proxy=Proxy.NGINX, subpath="spoolman")
    stack = runner.bring_up(s)
    try:
        runner.wait_healthy(stack)          # hits <host>/spoolman/api/v1/health
        contract.run(stack)
        # The SPA is served under the sub-path and config.js carries the base path:
        cfg = httpx.get(f"http://localhost:{stack.host_port}/spoolman/config.js", timeout=10)
        assert "SPOOLMAN_BASE_PATH" in cfg.text and "spoolman" in cfg.text
    finally:
        runner.tear_down(stack)
```

- [ ] **Step 3: Implement the proxy branch of `compose.render`**

Add a `proxy` service to the rendered compose `services`, render the chosen template with
`{{SUBPATH}}` filled, mount it into the proxy image (`nginx:alpine` / `traefik:v3` / `caddy:2`),
publish `host_port:80`, and remove the `ports` mapping from `spoolman` (internal only). Keep the DB
service. Write the rendered proxy config to a temp file alongside the compose file and bind-mount
it.

- [ ] **Step 4: Run the nginx test, then add + run traefik and caddy analogues**

Run: `uv run pytest tests_scenarios/tests/test_proxy_scenarios.py -v -s`
Add `test_traefik_root_serves_api` and `test_caddy_subpath_serves_api` mirroring Step 2 for the
other two proxies; run each to green.

- [ ] **Step 5: Commit**

```bash
git add tests_scenarios/proxies/ tests_scenarios/compose.py tests_scenarios/tests/test_proxy_scenarios.py
git commit -m "feat(scenarios): nginx/traefik/caddy proxy overlays with sub-path + forwarded headers"
```

---

## Phase 8 — Parallel scheduler

### Task 12: `scheduler.run_many` + `test-all` with filters

**Files:**
- Create: `tests_scenarios/scheduler.py`
- Modify: `tests_scenarios/__main__.py` — add `test-all` subcommand with `--tags/--db/--auth/--proxy/--arch/-j/--full/--quick`
- Test: `tests_scenarios/tests/test_scheduler.py` (no docker — inject a fake run function)

**Interfaces:**
- `async run_many(scenarios, *, concurrency_budget, run_one) -> list[Result]` where
  `Result = namedtuple("Result", "scenario ok detail")`; the scheduler admits scenarios while the
  sum of in-flight `scenario.weight()` stays ≤ `concurrency_budget`.

- [ ] **Step 1: Write the failing test (pure — no docker)**

```python
# tests_scenarios/tests/test_scheduler.py
import asyncio
from tests_scenarios.catalog import Arch, Db, Scenario
from tests_scenarios.scheduler import run_many


def test_respects_weight_budget_and_runs_all():
    seen, inflight, peak = [], 0, 0

    async def run_one(s):
        nonlocal inflight, peak
        inflight += s.weight(); peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        inflight -= s.weight(); seen.append(s.name)
        return True, "ok"

    scenarios = [Scenario(f"s{i}", Db.SQLITE, arch=Arch.ARMV7) for i in range(4)]  # weight 6 each
    results = asyncio.run(run_many(scenarios, concurrency_budget=6, run_one=run_one))
    assert len(results) == 4 and all(r.ok for r in results)
    assert peak <= 6  # never more than one armv7 (weight 6) at a time
```

- [ ] **Step 2: Run to verify it fails, implement, verify pass**

```python
# tests_scenarios/scheduler.py
"""Weight-aware async worker pool for running many scenarios in parallel."""
from __future__ import annotations

import asyncio
from collections import namedtuple

Result = namedtuple("Result", "scenario ok detail")


async def run_many(scenarios, *, concurrency_budget: int, run_one) -> list[Result]:
    sem = asyncio.Semaphore(concurrency_budget)
    results: list[Result] = []

    async def worker(s):
        weight = s.weight()
        for _ in range(weight):
            await sem.acquire()
        try:
            ok, detail = await run_one(s)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, repr(e)
        finally:
            for _ in range(weight):
                sem.release()
        results.append(Result(s, ok, detail))

    await asyncio.gather(*(worker(s) for s in scenarios))
    return results
```

Run: `uv run pytest tests_scenarios/tests/test_scheduler.py -v` → PASS.

- [ ] **Step 3: Wire `test-all` in the CLI**

Add a `cmd_test_all` that builds the scenario set (`CORE` by default, or `expand(...)` from the
filter flags), computes `concurrency_budget` (default = `os.cpu_count()`), and calls `run_many`
with a `run_one` that does bring_up → wait → contract/(integration+e2e unless `--quick`) → down,
printing a final pass/fail table. `--full` forces integration+e2e even on arch scenarios (already
the default per spec); `--quick` swaps to contract-only.

- [ ] **Step 4: Run a real parallel core sweep (excluding armv7 for speed here)**

Run: `uv run poe scenario test-all --quick -j 8`
Expected: the amd64 core scenarios come up in parallel and report a pass table.

- [ ] **Step 5: Commit**

```bash
git add tests_scenarios/scheduler.py tests_scenarios/__main__.py tests_scenarios/tests/test_scheduler.py
git commit -m "feat(scenarios): weight-aware parallel scheduler + test-all with filters"
```

---

## Phase 9 — Arch axis (armv7/arm64 under QEMU, full engines)

### Task 13: Per-arch image build + `armv7-sqlite` scenario

**Files:**
- Modify: `tests_scenarios/runner.py` — build the server image for `scenario.arch` via buildx
  before `up`, tagged `spoolman:scn-<arch>`, cached; point the rendered compose at that tag.
- Modify: `tests_scenarios/compose.py` — use the arch-specific image tag + `platform:` key.
- Test: `tests_scenarios/tests/test_arch_scenario.py` (docker+buildx+binfmt guarded, slow)

**Interfaces:** `runner.ensure_image(arch) -> str` returns the image tag, building once per arch
via `buildx build --platform <p> --load -t spoolman:scn-<arch> .` after ensuring `client/dist`.

- [ ] **Step 1: Write the failing (slow, guarded) test**

```python
# tests_scenarios/tests/test_arch_scenario.py
import shutil
import pytest
from tests_scenarios import runner
from tests_scenarios.assertions import contract
from tests_scenarios.catalog import Arch, Db, Scenario

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker+buildx required")


@pytest.mark.slow
def test_armv7_boots_and_serves():
    s = Scenario("armv7-sqlite-selftest", Db.SQLITE, arch=Arch.ARMV7)
    stack = runner.bring_up(s)
    try:
        runner.wait_healthy(stack, timeout=600)  # QEMU is slow
        contract.run(stack)
    finally:
        runner.tear_down(stack)
```

- [ ] **Step 2: Implement `ensure_image` + arch wiring; register the QEMU emulator**

`runner.bring_up` calls `ensure_image(scenario.arch)`; for non-amd64 it first runs
`docker run --privileged --rm tonistiigi/binfmt --install all` (idempotent) then the buildx build.
`compose.render` sets `image: <tag>` and `platform: <scenario.platform()>` on the `spoolman`
service. Confirm buildx is present (it is, per machine setup); if `--load` rejects multi-arch,
build the single target arch only.

- [ ] **Step 3: Run the slow test, then commit**

Run: `uv run pytest tests_scenarios/tests/test_arch_scenario.py -v -s -m slow`
Expected: PASS (minutes). Then:
```bash
git add tests_scenarios/runner.py tests_scenarios/compose.py tests_scenarios/tests/test_arch_scenario.py
git commit -m "feat(scenarios): per-arch buildx images + armv7 scenario under QEMU"
```

---

## Phase 10 — Manual UX, seeding, docs

### Task 14: `seed/sample.py` deterministic dataset

**Files:**
- Create: `tests_scenarios/seed.py`
- Test: `tests_scenarios/tests/test_seed.py` (docker-guarded, sqlite)

**Interfaces:** `seed_sample(stack) -> dict[str, int]` posts a fixed set of vendors/filaments/
spools through the API (honoring auth) and returns counts; idempotent-enough for a fresh stack.

- [ ] **Step 1: Write the failing test**

```python
# tests_scenarios/tests/test_seed.py
import shutil
import httpx
import pytest
from tests_scenarios import runner
from tests_scenarios.seed import seed_sample
from tests_scenarios.catalog import Db, Scenario

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


def test_seed_creates_expected_counts():
    stack = runner.bring_up(Scenario("sqlite-seed-selftest", Db.SQLITE))
    try:
        runner.wait_healthy(stack)
        counts = seed_sample(stack)
        assert counts["vendors"] >= 1 and counts["filaments"] >= 1 and counts["spools"] >= 1
        got = httpx.get(f"{stack.url}/api/v1/spool", timeout=10).json()
        assert len(got) == counts["spools"]
    finally:
        runner.tear_down(stack)
```

- [ ] **Step 2: Implement `seed.py`, run, commit**

Post 1 vendor → 2 filaments → 3 spools (honoring the token header from `scenario.test_env()`),
return counts. Run: `uv run pytest tests_scenarios/tests/test_seed.py -v -s` → PASS.
```bash
git add tests_scenarios/seed.py tests_scenarios/tests/test_seed.py
git commit -m "feat(scenarios): deterministic sample-data seeding for manual scenarios"
```

### Task 15: README + memory note

**Files:**
- Create: `tests_scenarios/README.md`
- Modify: user memory (see below)

- [ ] **Step 1: Write `tests_scenarios/README.md`** — document the CLI verbs, the axes, the core
  catalog, the two seams (integration conftest env vars, Playwright external mode), the machine
  constraints (compose v1, prebuilt client, buildx/binfmt for arch), and the manual-tester flow
  (`up` → summary block → `down`).

- [ ] **Step 2: Add a memory pointer** at
  `/home/sam/.claude/projects/-home-sam-spoolman-Spoolman/memory/` capturing the local run recipe
  (one file + one `MEMORY.md` line), linking `[[spoolman-build-test-gotchas]]`.

- [ ] **Step 3: Commit**

```bash
git add tests_scenarios/README.md
git commit -m "docs(scenarios): harness README + local run recipe"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** §3 architecture → Tasks 3–13; §4 model → Task 3; §5 core+expansion →
  Task 3 (`CORE`, `expand`) + Task 12 (`test-all` filters); §6 orchestration → Tasks 4,5,12; §7
  seams → Tasks 1,2,7,8; §8 manual UX → Task 6 (`_print_summary`) + Task 14; §9 seeding → Task 14;
  §10 arch → Task 13; §11 CI local-only → Global Constraints (no workflow shipped); §12 harness
  self-tests → Tasks 3,4,12 (no-docker) + guarded docker tests throughout.
- **Placeholder scan:** the two "discover the contract first" steps (Task 10 user-creation
  endpoint, Task 5 base-service key/port) are explicit *read-the-file* steps, not deferred code —
  each names the exact file to read and what to confirm, because those facts live in files this
  plan must not guess at.
- **Type consistency:** `ScenarioStack` fields, `Scenario` field names/enums, `run_many` /
  `Result`, and the env-var names (`SPOOLMAN_TEST_URL/TOKEN/LOGIN`, `PLAYWRIGHT_TARGET_URL/BASE/
  TOKEN`) are used identically across every task that references them.

## Risks called out for the executor

- The exact server **image tag** and **service key/internal port** in
  `tests_integration/docker-compose-*.yml` must be confirmed in Task 5 before `compose.render`
  is trusted — the plan assumes service `spoolman` on `8000`.
- The **user-creation + login** API contract (Task 10) must be read from the router, not assumed.
- **armv7 full engines** (integration suite + Playwright under QEMU) are intentionally slow; the
  self-test uses `contract` only, while `test-all --arch armv7` runs the full engines per the spec.
