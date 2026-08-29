import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests for the pages this fork adds to the Svelte client (client_v2).
 *
 * Separate from tests_frontend_v2, which is upstream's suite vendored verbatim as a subtree.
 * Keeping them apart means a red run names its owner: a failure here is ours, a failure there
 * is a regression against upstream's own expectations. It also keeps this suite editable --
 * anything written into the vendored tree conflicts on the next `git subtree pull`.
 *
 * The @playwright/test version is pinned exactly, not caret-ranged, to the version the vendored
 * suite resolves to. Playwright ties each release to a specific browser build -- 1.62.0 ->
 * 1.62.1 moves chromium from build 1234 to a later one -- so a caret would let the two suites
 * drift onto different browsers and download two of them in CI, where they otherwise share the
 * one `playwright install` already run for the vendored suite.
 *
 * PLAYWRIGHT_CHROMIUM_PATH points the run at an already-present browser instead, for sandboxes
 * that pre-install one and block downloads. Unset in CI, which installs the matching build.
 */
const baseURL = process.env.SPOOLMAN_BASE_URL ?? "http://localhost:8001";

/**
 * The authenticated specs need their own backends, started with SPOOLMAN_API_TOKEN set.
 *
 * They cannot share the one above: turning auth on there would answer 401 to every other spec in
 * this suite. And they need one backend each, not one between them, because seeding a user
 * account is irreversible -- the backend refuses to delete the last administrator, so
 * accounts_enabled can never return to false. One instance for both would leave the token specs
 * asserting a token field against a login form on every rerun and every CI retry.
 *
 * Running `npx playwright test` locally without those instances will fail these projects only --
 * use `--project=chromium` to skip them.
 */
const authBaseURL = process.env.SPOOLMAN_AUTH_BASE_URL ?? "http://localhost:8003";
const authAccountsBaseURL = process.env.SPOOLMAN_AUTH_ACCOUNTS_BASE_URL ?? "http://localhost:8004";

export default defineConfig({
  testDir: "./tests",
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // One shared Spoolman instance and one shared database, so tests run serially.
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL,
    ...(process.env.PLAYWRIGHT_CHROMIUM_PATH
      ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } }
      : {}),
    // Pin locale so date and number formatting is deterministic regardless of the runner.
    locale: "en-US",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    {
      // These override the top-level testDir, so ./tests-auth runs here and nowhere else.
      name: "auth-token",
      testDir: "./tests-auth",
      testMatch: /token\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], baseURL: authBaseURL },
    },
    {
      name: "auth-accounts",
      testDir: "./tests-auth",
      testMatch: /accounts\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], baseURL: authAccountsBaseURL },
    },
  ],
});
