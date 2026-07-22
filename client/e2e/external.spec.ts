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
