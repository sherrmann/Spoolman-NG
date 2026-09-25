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

/** The phone layout's bottom navigation bar, and the More sheet it opens. */
function bottomNav(page: Page): Locator {
  return page.locator("nav.bottom-nav");
}
function moreSheet(page: Page): Locator {
  return page.getByRole("dialog", { name: "More pages" });
}

test.describe("navigation", () => {
  test("the header is one row and the page keeps most of the screen", async ({ page }) => {
    // The header once stacked a second row of scrolling tabs, and a footer took a strip at the
    // bottom: together about 150px of a 727px screen on every page. Navigation moved to a bottom
    // bar and the footer went, so the fixed chrome now has a budget.
    await open(page, "/");
    const vh = page.viewportSize()!.height;
    const header = (await page.locator("header.topbar").boundingBox())!;
    const nav = (await bottomNav(page).boundingBox())!;
    expect(header.height, "the header should be a single row").toBeLessThanOrEqual(60);
    expect(nav.height, "the bottom bar").toBeLessThanOrEqual(64);
    expect(header.height + nav.height, "header and bottom bar together").toBeLessThanOrEqual(vh * 0.17);
    // The bar sits on the bottom edge, not floating over content above it.
    expect(Math.round(nav.y + nav.height)).toBe(vh);
    await expect(page.locator("footer")).toHaveCount(0);
  });

  test("the bottom bar and its More sheet reach every page the desktop navigation does", async ({ page }) => {
    // The desktop tab row is in the DOM but hidden at this width; its links are the list of
    // pages. A page that is in it but in neither the bar nor the sheet is unreachable on a phone.
    await open(page, "/");
    await expect(page.locator(".nav-desktop")).toBeHidden();
    const desktop = await page
      .locator(".nav-desktop a.tab[href^='/']")
      .evaluateAll((els) => els.map((e) => e.getAttribute("href")!));
    expect(desktop.length).toBeGreaterThan(5);

    const inBar = await bottomNav(page)
      .locator("a[href]")
      .evaluateAll((els) => els.map((e) => e.getAttribute("href")!));
    await bottomNav(page).getByRole("button", { name: "More" }).tap();
    await expect(moreSheet(page)).toBeVisible();
    const inSheet = await moreSheet(page)
      .locator("a[href^='/']")
      .evaluateAll((els) => els.map((e) => e.getAttribute("href")!));

    expect([...inBar, ...inSheet].sort()).toEqual([...desktop].sort());
    expect(inBar.length, "four pages in the bar, the rest under More").toBe(4);
  });

  test("tapping a bottom-bar page navigates and marks it current", async ({ page }) => {
    await open(page, "/");
    const links = bottomNav(page).locator("a[href]");
    const hrefs = await links.evaluateAll((els) => els.map((e) => e.getAttribute("href")!));
    for (const href of hrefs) {
      await test.step(href, async () => {
        const link = bottomNav(page).locator(`a[href="${href}"]`);
        await expectInViewport(page, `the ${href} link`, await link.boundingBox());
        await link.tap();
        // Compared on the path alone: pages may add a query string on arrival.
        await expect.poll(() => new URL(page.url()).pathname).toBe(href);
        await expect(link).toHaveAttribute("aria-current", "page");
        await expect(bottomNav(page).locator("[aria-current='page']")).toHaveCount(1);
      });
    }
  });

  test("the More sheet opens every other page and closes behind it", async ({ page }) => {
    await open(page, "/");
    const more = bottomNav(page).getByRole("button", { name: "More" });

    await more.tap();
    await expect(more).toHaveAttribute("aria-expanded", "true");
    await expectInViewport(page, "the More sheet", await moreSheet(page).boundingBox());
    await expectCleanLayout(page, "the More sheet");

    await moreSheet(page).getByRole("link", { name: "Settings" }).tap();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(moreSheet(page)).toHaveCount(0);
    // On a page the sheet holds, More is where you are.
    await expect(more).toHaveClass(/active/);

    await test.step("closes by its button, the backdrop and Escape", async () => {
      await more.tap();
      await moreSheet(page).getByRole("button", { name: "Close" }).tap();
      await expect(moreSheet(page)).toHaveCount(0);
      await expect(more).toBeFocused();

      await more.tap();
      await page.mouse.click(20, 20);
      await expect(moreSheet(page)).toHaveCount(0);

      await more.tap();
      await page.keyboard.press("Escape");
      await expect(moreSheet(page)).toHaveCount(0);
    });
  });

  test("the More sheet keeps keyboard focus inside it", async ({ page }) => {
    // It is modal: tabbing past its last control must wrap to its first, and back, rather than
    // walk into the page behind the backdrop.
    await open(page, "/");
    await bottomNav(page).getByRole("button", { name: "More" }).tap();
    const sheet = moreSheet(page);
    await expect(sheet.locator("a[href]").first()).toBeFocused();
    const count = await sheet.locator("a[href], button:not([disabled])").count();
    const inSheet = () => sheet.evaluate((el) => el.contains(document.activeElement));
    for (let i = 0; i < count + 2; i++) {
      await page.keyboard.press("Tab");
      expect(await inSheet(), `after ${i + 1} Tab presses`).toBe(true);
    }
    for (let i = 0; i < count + 2; i++) {
      await page.keyboard.press("Shift+Tab");
      expect(await inSheet(), `after ${i + 1} Shift+Tab presses`).toBe(true);
    }
  });

  test("the More sheet carries the version and this project's links", async ({ page }) => {
    await open(page, "/");
    await bottomNav(page).getByRole("button", { name: "More" }).tap();
    const sheet = moreSheet(page);
    await expect(sheet.getByText(/Spoolman NG\sv\d/)).toBeVisible();
    await expect(sheet.getByRole("link", { name: "Report an issue" })).toHaveAttribute(
      "href",
      "https://github.com/sherrmann/Spoolman-NG/issues",
    );
  });

  test("the library toolbar takes at most two rows", async ({ page }) => {
    // Filter, grid view and select once wrapped onto a row each beside the group/sort cluster.
    await open(page, "/");
    const toolbar = page.getByRole("toolbar").first();
    const box = (await toolbar.boundingBox())!;
    expect(box.height).toBeLessThanOrEqual(2 * 44 + 3 * 10);
    for (const name of ["Grid view", "Select"]) {
      await expectInViewport(page, `the ${name} button`, await toolbar.getByRole("button", { name }).boundingBox());
    }
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
      // Centred vertically, so a stepper resting on the sheet's bottom edge is not a sub-pixel miss.
      await stepper.evaluate((el) => el.scrollIntoView({ block: "center", inline: "nearest" }));
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
        const button = page.getByRole("button", { name }).first();
        await button.tap();
        await expectCleanLayout(page, `the library with the ${name} menu open`);
        // The same button closes it again. (Escape only does so from the menu's search box.)
        // This tap also fails if the open menu covers its own button, which it once did once
        // the group/sort buttons wrapped onto a second toolbar row.
        await button.tap();
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
