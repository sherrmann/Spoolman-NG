import { expect, test, type Page } from "@playwright/test";
import { seedLabelDesign, seedSpool } from "./helpers";

/**
 * The fork's pre-print checklist on /labels
 * (client_v2/src/lib/ng/components/PrePrintChecklist.svelte, gated in PrintLayoutPanel).
 *
 * `window.print()` is replaced with a counter before any app code runs -- both because the real
 * dialog would stall the session (which is why the vendored labels spec only ever exports
 * files) and because "did the print actually fire?" is the whole question here. The counter
 * lives on `window`, so it starts again at zero after a reload; each assertion below is
 * therefore about the prints made since the current page load.
 */

const SKIP_KEY = "spoolman-v2-skip-print-checklist";

/** The panel's own print button -- "Print 1 label", not the page's "Print" tab. */
const printButton = (page: Page) => page.getByRole("button", { name: /^Print \d+ label/ });
const dialog = (page: Page) => page.getByRole("dialog", { name: "Before you print" });
const prints = (page: Page) => page.evaluate(() => (window as unknown as { __prints: number }).__prints);

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    (window as unknown as { __prints: number }).__prints = 0;
    window.print = () => {
      (window as unknown as { __prints: number }).__prints++;
    };
  });
});

/**
 * Land on the print tab with one spool already selected. `?spools=<id>` is the deep link the
 * library's "print label" action uses, and it both opens that tab and ticks the spool, so the
 * print button is live as soon as the inventory has loaded.
 */
async function openPrintPanel(page: Page, spoolId: number) {
  await page.goto(`/labels?spools=${spoolId}`, { waitUntil: "networkidle" });
  await expect(printButton(page)).toBeEnabled();
}

test("the checklist stands between the print button and the browser's print dialog", async ({
  page,
  request,
}) => {
  await seedLabelDesign(request);
  const { spoolId } = await seedSpool(request, "PcCancel", "Shelf P");

  await openPrintPanel(page, spoolId);
  // A leftover opt-out from an earlier run of this spec would silence the dialog entirely.
  await page.evaluate((k) => localStorage.removeItem(k), SKIP_KEY);

  await printButton(page).click();

  await expect(dialog(page)).toBeVisible();
  await expect(dialog(page).getByText(/Scale is 100%/)).toBeVisible();
  // The seeded design is in sheet mode on A4 portrait, which is the page size printLabels
  // will ask the browser for -- not the 50 × 25 mm label.
  await expect(dialog(page).getByText("The selected paper size is exactly 210 × 297 mm.")).toBeVisible();
  await expect(dialog(page).getByText(/Margins are set to/)).toBeVisible();
  await expect(dialog(page).getByText(/Headers and footers are turned off/)).toBeVisible();

  await dialog(page).getByRole("button", { name: "Cancel" }).click();

  await expect(dialog(page)).toHaveCount(0);
  // Cancelling means exactly that: no print, and no opt-out written either.
  expect(await prints(page)).toBe(0);
  expect(await page.evaluate((k) => localStorage.getItem(k), SKIP_KEY)).toBeNull();
});

test("printing now, with the opt-out ticked, is remembered for the next print", async ({ page, request }) => {
  await seedLabelDesign(request);
  const { spoolId } = await seedSpool(request, "PcSkip", "Shelf Q");

  await openPrintPanel(page, spoolId);
  await page.evaluate((k) => localStorage.removeItem(k), SKIP_KEY);

  await printButton(page).click();
  await dialog(page).getByRole("checkbox", { name: "Don't show this again" }).check();
  await dialog(page).getByRole("button", { name: "Print now" }).click();

  await expect(dialog(page)).toHaveCount(0);
  // printLabels rasterises each label before it calls print, so the count arrives a moment
  // after the click.
  await expect.poll(() => prints(page)).toBe(1);
  expect(await page.evaluate((k) => localStorage.getItem(k), SKIP_KEY)).toBe("1");

  // The opt-out is per browser, so it survives the reload -- and the print button now goes
  // straight through. The counter is back at zero because it lives on the reloaded window.
  await openPrintPanel(page, spoolId);
  expect(await prints(page)).toBe(0);

  await printButton(page).click();

  await expect.poll(() => prints(page)).toBe(1);
  await expect(dialog(page)).toHaveCount(0);
});
