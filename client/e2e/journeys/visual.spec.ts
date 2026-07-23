import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Local-only visual regression. Baselines are rendered on the dev machine (font/GPU
// dependent), so this suite only runs when E2E_VISUAL=1 (npm run test:visual) and never
// in CI. Screens are data-independent (forms, help, settings) so a reused dev server
// with leftover journey data cannot dirty the pixels. Rebaseline after an intentional
// UI change with: npm run test:visual -- --update-snapshots
test.skip(!process.env.E2E_VISUAL, "visual baselines are local-only; run via npm run test:visual");

const SCREENS: Array<[name: string, route: string]> = [
  ["help", "/help"],
  ["settings", "/settings"],
  ["spool-create", "/spool/create"],
  ["filament-create", "/filament/create"],
  ["vendor-create", "/vendor/create"],
];

test.describe("visual regression (static screens)", () => {
  for (const [name, route] of SCREENS) {
    test(`${name} renders unchanged`, async ({ page }) => {
      await page.goto(`${APP_BASE_URL}${route}`);
      await expect(page.locator(".ant-layout").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      await expect(page).toHaveScreenshot(`${name}.png`, {
        fullPage: true,
        animations: "disabled",
        maxDiffPixels: 150,
      });
    });
  }
});
