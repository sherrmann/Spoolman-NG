import { expect, test, type Page } from "@playwright/test";
import { openOrdersFor, seedInventory, seedLowFilament, thresholdOf, type Seeded } from "./helpers";

/**
 * The fork's Low Stock page (client_v2/src/routes/lowstock/).
 *
 * Unlike Home, this page writes: it edits a filament's threshold and places orders. So the
 * assertions here check the API afterwards rather than the DOM alone -- a row can show an
 * "Ordered" pill from optimistic local state while the request that was supposed to create the
 * order silently failed, and only the server knows which happened.
 */

let seeded: Seeded;

test.beforeAll(async ({ playwright, baseURL }) => {
  const api = await playwright.request.newContext({ baseURL });
  seeded = await seedInventory(api);
  await api.dispose();
});

async function openLowStock(page: Page) {
  await page.goto("/lowstock", { waitUntil: "networkidle" });
  await expect(page.getByRole("listitem").first()).toBeVisible();
}

const row = (page: Page, name: string) =>
  page.getByRole("listitem").filter({ hasText: name }).first();

test("lists both low-stock sections and marks what is already on order", async ({ page }) => {
  await openLowStock(page);

  await expect(page).toHaveTitle(/Low Stock/);
  // Both routes into "low" are computed by different branches, so both need a row.
  await expect(row(page, seeded.explicitLowName)).toBeVisible();
  await expect(row(page, seeded.fallbackLowName)).toBeVisible();

  await expect(row(page, seeded.orderedName).locator(".pill")).toHaveText(/Ordered/);
  // The un-ordered row must not carry one, or a pill rendered unconditionally would pass above.
  await expect(row(page, seeded.fallbackLowName).locator(".pill")).toHaveCount(0);
});

test("editing a threshold persists it to the filament", async ({ page, request }) => {
  const filament = await seedLowFilament(request, "Thr");
  expect(await thresholdOf(request, filament.id)).toBeNull();

  await openLowStock(page);
  const target = row(page, filament.name);
  await target.getByRole("button", { name: /threshold/i }).click();

  // Located at page level, not inside the row: the editor renders through a portal, so it is not
  // a descendant of the row that opened it. It is also a text input with inputmode=decimal
  // rather than a number input, so it is a textbox and not a spinbutton.
  const popover = page.getByRole("dialog", { name: /threshold/i });
  await expect(popover).toBeVisible();
  const input = popover.getByRole("textbox");
  await input.fill("275");
  await input.press("Enter");

  // Polled against the API, not asserted on the button's label: the label would update from
  // local state whether or not the PATCH reached the server.
  await expect
    .poll(() => thresholdOf(request, filament.id), { timeout: 10_000 })
    .toBe(275);
});

test("marking a filament as ordered creates an open order for it", async ({ page, request }) => {
  const filament = await seedLowFilament(request, "Ord");
  expect(await openOrdersFor(request, filament.id)).toHaveLength(0);

  await openLowStock(page);
  const target = row(page, filament.name);
  await target.getByRole("button", { name: /mark as ordered/i }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /mark as ordered/i }).click();

  await expect
    .poll(() => openOrdersFor(request, filament.id).then((o) => o.length), { timeout: 10_000 })
    .toBe(1);

  // And the row reflects it without a manual reload, which is the point of refreshing on success.
  await expect(row(page, filament.name).locator(".pill")).toHaveText(/Ordered/, { timeout: 10_000 });
});

test("the dialog can be dismissed without placing an order", async ({ page, request }) => {
  const filament = await seedLowFilament(request, "Esc");

  await openLowStock(page);
  await row(page, filament.name)
    .getByRole("button", { name: /mark as ordered/i })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  expect(await openOrdersFor(request, filament.id)).toHaveLength(0);
});

test("the page scrolls inside the app shell rather than overflowing it", async ({ page }) => {
  // The same guard the Home page carries: the shell is height:100dvh and pages scroll within it.
  // A page that grows the document instead puts the footer through its own content.
  await page.setViewportSize({ width: 700, height: 800 });
  await openLowStock(page);

  const { docScroll, viewport, pageScrolls } = await page.evaluate(() => {
    const el = document.querySelector(".page") as HTMLElement | null;
    return {
      docScroll: document.documentElement.scrollHeight,
      viewport: window.innerHeight,
      pageScrolls: el ? el.scrollHeight > el.clientHeight : false,
    };
  });

  expect(
    docScroll,
    `the document grew to ${docScroll}px against a ${viewport}px viewport`,
  ).toBeLessThanOrEqual(viewport + 1);
  expect(pageScrolls, "seeded content should overflow the pane at 700x800").toBe(true);
});
