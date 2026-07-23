import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Axe scan of the key screens, gated to serious/critical WCAG A/AA violations so the
// suite fails on real regressions without drowning in advisory noise. Pre-existing debt
// goes in KNOWN_ISSUES with a reason — any new rule failing still fails the run.
const KNOWN_ISSUES: Record<string, string> = {
  // All three ship in the app shell's antd sidebar, on every screen (baseline 2026-07-22):
  "aria-required-children":
    "antd Menu puts non-menuitem children inside role=menu; fixing means reworking the refine/antd sidebar markup",
  listitem: "same antd Menu markup: an <li> rendered outside a <ul>/<ol>",
  "color-contrast":
    "sidebar/theme palette below 4.5:1 on ~9 nodes; a theme change is a visible UI change needing design review",
  // Screen-specific antd-internal or multi-site debt (baseline 2026-07-22):
  "aria-allowed-attr": "antd Select sets unsupported ARIA attrs on its focus wrapper (.ant-select-focused)",
  label:
    "4 antd InputNumber group-wrapper inputs on the create forms lack a programmatic label; " +
    "needs per-field aria-labels wired through i18n",
  "nested-interactive": "antd PageHeader nests its back button inside an interactive header",
  "scrollable-region-focusable": "antd Table's scroll body is not keyboard-focusable",
};

async function seriousViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  return results.violations
    .filter((v) => (v.impact === "serious" || v.impact === "critical") && !(v.id in KNOWN_ISSUES))
    .map((v) => `${v.id} (${v.impact}): ${v.help} — ${v.nodes.length} node(s), e.g. ${v.nodes[0]?.target}`);
}

const SCREENS: Array<[name: string, route: string]> = [
  ["home", "/"],
  ["spool list", "/spool"],
  ["new spool form", "/spool/create"],
  ["settings", "/settings"],
  ["help", "/help"],
];

test.describe("accessibility (axe, serious+critical)", () => {
  for (const [name, route] of SCREENS) {
    test(`${name} has no serious violations`, async ({ page }) => {
      await page.goto(`${APP_BASE_URL}${route}`);
      // The app shell (sidebar) proves the SPA booted; networkidle settles data loads.
      await expect(page.locator(".ant-layout").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      expect(await seriousViolations(page)).toEqual([]);
    });
  }
});
