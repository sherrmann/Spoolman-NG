import { expect, test, type Locator, type Page } from "@playwright/test";
import { post, seedLocation, seedOrder, unique } from "../helpers";
import { expectCleanLayout, expectInViewport, PHONE_WIDTHS } from "./layout";

/**
 * The Svelte client on a phone.
 *
 * Every other spec in this suite runs at desktop size, and the client switches to a different
 * layout below 860px: a collapsed search, an icon-only add button, a scrolling tab strip, and the
 * inspector as a bottom sheet instead of a side pane. None of that was exercised, and it is how
 * the companion app (mobile/) shows the whole UI.
 *
 * The checks are the defects a phone user actually hits, rather than pixel snapshots: sideways page
 * scroll, controls pushed or clipped out of reach, a dialog taller or wider than the screen, the
 * current page's tab hidden off the end of the strip, and a sheet that will not close.
 */

/** Every top-level page. The location detail page is added once one exists. */
const ROUTES = [
  "/",
  "/home",
  "/lowstock",
  "/orders",
  "/dashboard",
  "/locations",
  "/calibration",
  "/labels",
  "/settings",
  "/help",
];

interface Seeded {
  filamentName: string;
  spoolId: number;
  locationId: number;
}

let seeded: Seeded;

test.beforeAll(async ({ playwright, baseURL }) => {
  const api = await playwright.request.newContext({ baseURL });
  // Long names on purpose (near the API's 64-character limit once suffixed): they are what
  // pushes a narrow layout past its edge.
  const vendor = await post(api, "/vendor", {
    name: unique("Mobile Vendor Long Registered Company Name GmbH"),
    empty_spool_weight: 190,
  });
  const filamentName = unique("Mobile Galaxy Black Silk Matte Filament Long Name");
  const filament = await post(api, "/filament", {
    name: filamentName,
    vendor_id: vendor.id,
    material: "PLA",
    color_hex: "1A1A2E",
    price: 24.99,
    density: 1.24,
    diameter: 1.75,
    weight: 1000,
    spool_weight: 190,
  });
  const location = await seedLocation(api, "Mobile Shelf");
  const spool = await post(api, "/spool", {
    filament_id: filament.id,
    used_weight: 350,
    location: location.name,
    lot_nr: unique("LOT"),
  });
  await post(api, "/spool", { filament_id: filament.id, used_weight: 900, location: location.name });
  // So the orders page renders its list rather than only the empty state.
  await seedOrder(api, "Mobile");
  await api.dispose();
  seeded = { filamentName, spoolId: spool.id, locationId: location.id };
});

/** Uncaught exceptions during a test. Console noise (e.g. the font CDN offline) is not counted. */
function trackPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function open(page: Page, path: string) {
  await page.goto(path, { waitUntil: "networkidle" });
  await expect(page.locator("header.topbar")).toBeVisible();
}

/** The library with at least one spool row listed. Which spools are on page one depends on what
 * the rest of the suite has created in the shared database, so the tests take the first row. */
async function openLibrary(page: Page) {
  await open(page, "/");
  await expect(spoolRow(page)).toBeVisible();
}

function spoolRow(page: Page): Locator {
  return page.locator("a.row").filter({ has: page.locator(".id") }).first();
}

/** The mobile inspector sheet (DetailPane) -- present in the DOM even while closed. */
function sheet(page: Page): Locator {
  return page.locator(".pane .sheet");
}

async function expectSheetOpen(page: Page) {
  // Open means slid fully up: its bottom edge sits on the viewport's bottom edge.
  await expect
    .poll(async () => {
      const box = await sheet(page).boundingBox();
      return box ? Math.round(box.y + box.height) : null;
    })
    .toBe(page.viewportSize()!.height);
}

async function expectSheetClosed(page: Page) {
  // Closed means translated fully below the viewport.
  await expect
    .poll(async () => {
      const box = await sheet(page).boundingBox();
      return box ? box.y >= page.viewportSize()!.height - 1 : true;
    })
    .toBe(true);
}

for (const width of PHONE_WIDTHS) {
  test.describe(`at ${width}px wide`, () => {
    test.use({ viewport: { width, height: 700 } });

    test("no page scrolls sideways or pushes a control out of reach", async ({ page }) => {
      const errors = trackPageErrors(page);
      for (const path of [...ROUTES, `/location/show/${seeded.locationId}`]) {
        await test.step(path, async () => {
          await open(page, path);
          await expectCleanLayout(page, path);
        });
      }
      expect(errors, "uncaught exceptions while loading the pages").toEqual([]);
    });

    test("the header's actions all fit on the screen", async ({ page }) => {
      await open(page, "/");
      for (const name of ["Search", "Add spools"]) {
        const button = page.getByRole("button", { name, exact: true });
        await expectInViewport(page, `the ${name} button`, await button.boundingBox());
      }
      const scan = page.locator("header .scan-btn");
      await expectInViewport(page, "the scan button", await scan.boundingBox());
    });
  });
}

test.describe("navigation", () => {
  test("the current page's tab is scrolled into view in the tab strip", async ({ page }) => {
    // The strip scrolls sideways at phone width. Landing on a page whose tab sits past the end of
    // it -- anything from Dashboard onwards -- must not leave the user unable to see where they are.
    for (const path of ["/settings", "/help", "/labels", "/calibration", "/"]) {
      await test.step(path, async () => {
        await open(page, path);
        const active = page.locator(".mobile-nav a.tab.active");
        await expect(active).toHaveCount(1);
        await expect(active).toBeInViewport({ ratio: 1 });
      });
    }
  });

  test("every tab can be reached and tapped from the strip", async ({ page }) => {
    await open(page, "/");
    const tabs = page.locator(".mobile-nav a.tab");
    const hrefs = await tabs.evaluateAll((els) => els.map((e) => e.getAttribute("href")!));
    expect(hrefs.length).toBeGreaterThan(5);
    for (const href of hrefs) {
      await test.step(href, async () => {
        const tab = page.locator(`.mobile-nav a.tab[href="${href}"]`);
        await tab.tap();
        // Compared on the path alone: pages may add a query string on arrival (?by= on the
        // dashboard).
        await expect.poll(() => new URL(page.url()).pathname).toBe(href);
        await expect(tab).toHaveClass(/active/);
      });
    }
  });

  test("the desktop navigation is not shown alongside the mobile one", async ({ page }) => {
    await open(page, "/");
    await expect(page.locator(".mobile-nav")).toBeVisible();
    await expect(page.locator(".nav-desktop")).toBeHidden();
    await expect(page.locator(".search-desktop")).toBeHidden();
  });
});

test.describe("library", () => {
  test("tapping a spool opens the inspector as a bottom sheet that fits the screen", async ({ page }) => {
    const errors = trackPageErrors(page);
    await openLibrary(page);
    await expectSheetClosed(page);

    const id = (await spoolRow(page).locator(".id").innerText()).trim();
    await spoolRow(page).tap();
    await expectSheetOpen(page);
    await expect(sheet(page)).toContainText(id);
    await expectCleanLayout(page, "the spool inspector sheet");

    // Leaves a gap above the sheet so the page behind stays recognisable (max-height 88%).
    const box = (await sheet(page).boundingBox())!;
    expect(box.y).toBeGreaterThan(0);
    expect(box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
    expect(errors).toEqual([]);
  });

  test("the inspector's number steppers can be tapped", async ({ page }) => {
    // A fixed-width number input once ran past the sheet's edge, hiding its +/- steppers where no
    // tap could reach them. Checked on the controls themselves, not just by layout measurement.
    await openLibrary(page);
    await spoolRow(page).tap();
    await expectSheetOpen(page);

    const steppers = sheet(page).getByRole("button", { name: "Increment" });
    const count = await steppers.count();
    expect(count, "the spool inspector should show number inputs").toBeGreaterThan(0);
    for (let i = 0; i < count; i++) {
      const stepper = steppers.nth(i);
      await stepper.scrollIntoViewIfNeeded();
      await expect(stepper).toBeInViewport({ ratio: 1 });
      // Reaching it must not have taken a sideways scroll of the sheet: Playwright will happily
      // scroll one to bring a clipped control into view, which a user would never think to do.
      expect(await sheet(page).locator(".sheet-body").evaluate((el) => el.scrollLeft)).toBe(0);
      // A trial tap runs every actionability check (visible, stable, not covered) without firing.
      await stepper.tap({ trial: true });
    }
  });

  test("the inspector sheet closes by its handle, the backdrop, and Escape", async ({ page }) => {
    await openLibrary(page);

    await test.step("the handle", async () => {
      await spoolRow(page).tap();
      await expectSheetOpen(page);
      await sheet(page).locator(".grabber").tap();
      await expectSheetClosed(page);
    });

    await test.step("the backdrop", async () => {
      await spoolRow(page).tap();
      await expectSheetOpen(page);
      // Tap the backdrop above the sheet, clear of it.
      await page.locator(".pane .scrim").tap({ position: { x: 20, y: 20 } });
      await expectSheetClosed(page);
    });

    await test.step("Escape", async () => {
      // Matters for a phone with a keyboard attached and for a narrow desktop window; it must
      // not depend on the backdrop having focus, which nothing ever gives it.
      await spoolRow(page).tap();
      await expectSheetOpen(page);
      await page.keyboard.press("Escape");
      await expectSheetClosed(page);
    });

    // Closed means out of the way: the header's buttons work again.
    await page.getByRole("button", { name: "Add spools", exact: true }).tap({ trial: true });
  });

  test("tapping a filament header opens the filament inspector", async ({ page }) => {
    await openLibrary(page);
    // The header's whole row is a stretched link. Its centre is covered by the manufacturer
    // link, so tap near its leading edge, over the swatch.
    await page.locator("a.main").first().tap({ position: { x: 12, y: 12 } });
    await expectSheetOpen(page);
    await expectCleanLayout(page, "the filament inspector sheet");
  });

  test("the search overlay covers the header and closes again", async ({ page }) => {
    await open(page, "/");
    await page.getByRole("button", { name: "Search", exact: true }).tap();
    const input = page.locator(".search-overlay input");
    await expect(input).toBeVisible();
    await expect(input).toBeFocused();
    await expectInViewport(page, "the search field", await input.boundingBox());
    await page.keyboard.type(seeded.filamentName);
    // It is a jump-to menu, not a list filter: the seeded filament shows with its spools.
    const result = page.getByText(`#${seeded.spoolId}`, { exact: true });
    await expect(result).toBeVisible();
    await expectCleanLayout(page, "the library with the search open");

    await page.locator(".search-back").tap();
    await expect(input).toBeHidden();
    await expect(page.getByRole("button", { name: "Add spools", exact: true })).toBeVisible();

    // And picking a result opens that spool, closing the search on the way.
    await page.getByRole("button", { name: "Search", exact: true }).tap();
    await page.keyboard.type(seeded.filamentName);
    await result.tap();
    await expectSheetOpen(page);
    await expect(input).toBeHidden();
    await expect(sheet(page)).toContainText(`#${seeded.spoolId}`);
  });

  test("the list toolbar's menus open within the screen", async ({ page }) => {
    await open(page, "/");
    // The grouping picker and the filter menu both open popovers anchored to the toolbar; a
    // popover anchored near the right edge is the usual thing to spill off a narrow screen.
    for (const name of [/Filter/, /^Filament/]) {
      await test.step(String(name), async () => {
        await page.getByRole("button", { name }).first().tap();
        await expectCleanLayout(page, `the library with the ${name} menu open`);
        await page.keyboard.press("Escape");
      });
    }
  });
});

test.describe("dialogs", () => {
  /** The open dialog must fit the screen, and so must its way out. */
  async function expectDialogFits(page: Page, what: string) {
    const dialog = page.getByRole("dialog").last();
    await expect(dialog).toBeVisible();
    await expectInViewport(page, what, await dialog.boundingBox());
    await expectCleanLayout(page, what);
  }

  test("adding spools opens a dialog that fits the screen", async ({ page }) => {
    await open(page, "/");
    await page.getByRole("button", { name: "Add spools", exact: true }).tap();
    await expectDialogFits(page, "the add-spools dialog");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("adding spools still fits at the smallest phone width", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 568 });
    await open(page, "/");
    await page.getByRole("button", { name: "Add spools", exact: true }).tap();
    await expectDialogFits(page, "the add-spools dialog at 320x568");
  });

  test("the new-order and new-location dialogs fit the screen", async ({ page }) => {
    await open(page, "/orders");
    await page.getByRole("button", { name: "New order" }).tap();
    await expectDialogFits(page, "the new-order dialog");
    await page.keyboard.press("Escape");

    await open(page, "/locations");
    await page.getByRole("button", { name: "New Location" }).tap();
    await expectDialogFits(page, "the new-location dialog");
  });
});
