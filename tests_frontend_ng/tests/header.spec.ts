import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { seedLowFilament } from "./helpers";
import { expectCleanLayout, expectInViewport } from "./mobile/layout";

/**
 * The header at laptop and desktop widths.
 *
 * With this fork's extra pages the tab row alone is about 850px, more with the low-stock count or
 * custom links, and below ~1500px the header was wider than the window: the search field, the scan
 * button and "Add spools" sat past its right edge, reachable only by scrolling the whole page
 * sideways. Now the tab row gives way -- it shrinks to the space left and scrolls within itself --
 * while the search field stays where upstream put it (upstream's own suite types into it at 1280).
 */

async function setSetting(request: APIRequestContext, key: string, value: unknown) {
  const res = await request.post(`/api/v1/setting/${key}`, {
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify(JSON.stringify(value)),
  });
  if (!res.ok()) throw new Error(`setting ${key} -> ${res.status()} ${await res.text()}`);
}

test.beforeAll(async ({ playwright, baseURL }) => {
  // The widest the row gets: a low-stock count on its tab and an operator's custom link.
  const api = await playwright.request.newContext({ baseURL });
  await seedLowFilament(api, "Header");
  await setSetting(api, "custom_links", [{ name: "Mainsail", url: "http://mainsail.local" }]);
  await api.dispose();
});

test.afterAll(async ({ playwright, baseURL }) => {
  const api = await playwright.request.newContext({ baseURL });
  await setSetting(api, "custom_links", []);
  await api.dispose();
});

async function expectHeaderActionsOnScreen(page: Page) {
  await expectInViewport(page, "the search field", await page.locator(".search-desktop input").boundingBox());
  await expectInViewport(page, "the scan button", await page.locator("header .scan-btn").boundingBox());
  await expectInViewport(page, "the add button", await page.locator(".add-desktop button").boundingBox());
}

for (const width of [1000, 1280, 1440, 1500, 1600]) {
  test(`at ${width}px the header fits and its actions are on screen`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/settings", { waitUntil: "networkidle" });
    // Wait for the late arrivals that widen the row.
    await expect(page.locator(".nav-desktop").getByRole("link", { name: /Mainsail/ })).toBeAttached();
    await expect(page.locator(".nav-desktop a.tab[href='/lowstock'] .badge")).toBeVisible();
    await expectCleanLayout(page, "/settings");
    await expectHeaderActionsOnScreen(page);
  });
}

test("the current page's tab stays in view when the tab row is too narrow", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 800 });
  for (const path of ["/help", "/settings", "/"]) {
    await page.goto(path, { waitUntil: "networkidle" });
    // The badge renders after first paint and pushes the later tabs right; the row must follow.
    await expect(page.locator(".nav-desktop a.tab[href='/lowstock'] .badge")).toBeVisible();
    const active = page.locator(".nav-desktop a.tab.active");
    await expect(active).toHaveCount(1);
    await expect(active).toBeInViewport({ ratio: 1 });
  }
  // The row scrolled, not the page.
  expect(await page.evaluate(() => window.scrollX)).toBe(0);
});

test("narrowing the window keeps the current page's tab in view", async ({ page }) => {
  // Snapping a window to half the screen or opening devtools narrows the row without a new page
  // or any change to the tabs themselves.
  await page.setViewportSize({ width: 1700, height: 800 });
  await page.goto("/settings", { waitUntil: "networkidle" });
  for (const width of [1200, 1000, 900]) {
    await page.setViewportSize({ width, height: 800 });
    await expect(page.locator(".nav-desktop a.tab.active"), `at ${width}px`).toBeInViewport({ ratio: 1 });
  }
});
