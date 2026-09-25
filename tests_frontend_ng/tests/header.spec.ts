import { expect, test, type Page } from "@playwright/test";
import { expectCleanLayout, expectInViewport } from "./mobile/layout";

/**
 * The header at laptop and tablet widths.
 *
 * With this fork's extra pages the tab row alone is about 850px, and below ~1500px the header was
 * wider than the window: the search field, the scan button and "Add spools" sat past its right
 * edge, reachable only by scrolling the whole page sideways. Now the search collapses to an icon
 * there and the tabs scroll inside their own space.
 */

async function expectHeaderActionsOnScreen(page: Page) {
  for (const name of ["Search", "Add spools"]) {
    const button = page.locator("header").getByRole("button", { name, exact: true }).filter({ visible: true });
    await expectInViewport(page, `the ${name} button`, await button.boundingBox());
  }
  await expectInViewport(page, "the scan button", await page.locator("header .scan-btn").boundingBox());
}

for (const width of [1000, 1280, 1440]) {
  test(`at ${width}px the header fits and its actions are on screen`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/settings", { waitUntil: "networkidle" });
    await expectCleanLayout(page, "/settings");
    await expectHeaderActionsOnScreen(page);
  });
}

test("the current page's tab is scrolled into view when the tab row is too narrow", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 800 });
  for (const path of ["/help", "/settings", "/"]) {
    await page.goto(path, { waitUntil: "networkidle" });
    const active = page.locator(".nav-desktop a.tab.active");
    await expect(active).toHaveCount(1);
    await expect(active).toBeInViewport({ ratio: 1 });
  }
  // The row scrolled, not the page.
  expect(await page.evaluate(() => window.scrollX)).toBe(0);
});

test("the collapsed search opens over the header and finds things", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 800 });
  await page.goto("/", { waitUntil: "networkidle" });
  await page.locator("header").getByRole("button", { name: "Search", exact: true }).click();
  const input = page.locator(".search-overlay input");
  await expect(input).toBeFocused();
  await expectInViewport(page, "the search field", await input.boundingBox());
  await page.locator(".search-back").click();
  await expect(input).toBeHidden();
});

test("at full width the search field is shown in the header as before", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/", { waitUntil: "networkidle" });
  await expect(page.locator(".search-desktop input")).toBeVisible();
  await expect(page.locator("header").getByRole("button", { name: "Search", exact: true })).toBeHidden();
  await expectHeaderActionsOnScreenWide(page);
});

async function expectHeaderActionsOnScreenWide(page: Page) {
  await expectInViewport(page, "the add button", await page.locator(".add-desktop button").boundingBox());
  await expectInViewport(page, "the search field", await page.locator(".search-desktop input").boundingBox());
}
