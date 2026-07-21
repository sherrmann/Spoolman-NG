import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";
import { APP_BASE_URL, INGRESS_BASE_URL, ROOT_BASE_URL, SUBPATH, SUBPATH_BASE_URL } from "./e2e/constants";

// The e2e suite runs the *built* client (so `npm run build` must have run) against
// four servers:
//   root    → http://127.0.0.1:30011/           static harness, root deploy (PWA tests)
//   subpath → http://127.0.0.1:30012/spoolman/  static harness, sub-path deploy (PWA tests)
//   app     → http://127.0.0.1:30013/           REAL backend (API + client + temp SQLite),
//                                                driven by the whole-app journey tests
//   ingress → http://127.0.0.1:30014/           REAL backend behind a simulated Home
//                                                Assistant ingress gateway (#211): requests
//                                                under /api/hassio_ingress/<token>/ arrive
//                                                prefix-stripped with X-Ingress-Path set,
//                                                everything else passes through directly
// When E2E_COVERAGE=1 the build carries inline source maps and a global teardown
// aggregates each test's V8 coverage back onto client/src (see e2e/coverage-*.ts).

const configDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(configDir, "..");

// In this sandbox Chromium is pre-installed and cannot be re-downloaded, so point
// Playwright at it. In CI the path is absent and Playwright uses the browser that
// `playwright install chromium` fetched (kept in lockstep with the pinned version).
const preinstalledChromium = "/opt/pw-browsers/chromium";
const launchOptions = existsSync(preinstalledChromium) ? { executablePath: preinstalledChromium } : {};

const serverCommand = "uv run python client/e2e/serve.py";

// When PLAYWRIGHT_TARGET_URL is set, skip booting the local webServer trio entirely
// and point Playwright at an already-running external stack (e.g. a scenario harness
// stood up by a later task), running only e2e/external.spec.ts against it.
const targetUrl = process.env.PLAYWRIGHT_TARGET_URL;

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
        testDir: "./e2e",
        testIgnore: /external\.spec\.ts$/,
        fullyParallel: true,
        forbidOnly: !!process.env.CI,
        retries: process.env.CI ? 2 : 0,
        // Retries exist to gather traces, not to hide flakiness: a pass-on-retry still
        // fails the run (a flaky journey masked a real backend 500 in a green CI run).
        failOnFlakyTests: true,
        // Journey tests share one real backend, so run them serially for isolation.
        workers: 1,
        reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
        timeout: 60_000,
        expect: { timeout: 15_000 },
        globalTeardown: "./e2e/coverage-teardown.ts",
        use: {
          trace: "on-first-retry",
          launchOptions,
        },
        projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
        webServer: [
          {
            command: serverCommand,
            cwd: repoRoot,
            env: { SPOOLMAN_BASE_PATH: "", PORT: "30011" },
            url: `${ROOT_BASE_URL}/config.js`,
            reuseExistingServer: !process.env.CI,
            timeout: 60_000,
          },
          {
            command: serverCommand,
            cwd: repoRoot,
            env: { SPOOLMAN_BASE_PATH: "spoolman", PORT: "30012" },
            url: `${SUBPATH_BASE_URL}${SUBPATH}/config.js`,
            reuseExistingServer: !process.env.CI,
            timeout: 60_000,
          },
          {
            // Real backend: fresh temp SQLite each run, serving API + built client.
            command:
              "rm -rf .e2e-data && mkdir -p .e2e-data && uv run uvicorn spoolman.main:app --host 127.0.0.1 --port 30013 --log-level warning",
            cwd: repoRoot,
            env: {
              SPOOLMAN_DB_TYPE: "sqlite",
              SPOOLMAN_DIR_DATA: path.join(repoRoot, ".e2e-data"),
              SPOOLMAN_LOGGING_LEVEL: "WARNING",
              // Keep the suite hermetic: no filament-DB sync from GitHub Pages, and 3DFP
              // profile lookups loop back to this server — the SPA fallback returns HTML
              // that parses to no profile, giving the error branch a deterministic 404
              // instead of a live call to 3dfilamentprofiles.com.
              EXTERNAL_DB_URL: "",
              EXTERNAL_3DFP_URL: APP_BASE_URL,
            },
            url: `${APP_BASE_URL}/api/v1/health`,
            reuseExistingServer: !process.env.CI,
            timeout: 120_000,
          },
          {
            // Real backend behind the simulated HA ingress gateway; own scratch SQLite.
            command:
              "rm -rf .e2e-data-ingress && mkdir -p .e2e-data-ingress && uv run python client/e2e/ingress_gateway.py",
            cwd: repoRoot,
            env: {
              SPOOLMAN_DB_TYPE: "sqlite",
              SPOOLMAN_DIR_DATA: path.join(repoRoot, ".e2e-data-ingress"),
              SPOOLMAN_LOGGING_LEVEL: "WARNING",
              SPOOLMAN_HA_INGRESS: "1",
              PORT: "30014",
              // Hermetic, like the app server above: no external filament-DB or 3DFP calls.
              EXTERNAL_DB_URL: "",
              EXTERNAL_3DFP_URL: INGRESS_BASE_URL,
            },
            // The direct (prefix-less) path must work on the same process — probing health
            // through it asserts the pass-through half of the gateway at startup.
            url: `${INGRESS_BASE_URL}/api/v1/health`,
            reuseExistingServer: !process.env.CI,
            timeout: 120_000,
          },
        ],
      },
);
