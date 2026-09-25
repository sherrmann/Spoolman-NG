import { expect, test, type Page } from "@playwright/test";
import { seedFilament, unique } from "./helpers";

/**
 * Gallery view for the Library (#412, step 3): a "Grid view" toggle that renders every spool as
 * a card instead of a row. See docs/design/library-table-parity.md, step 3.
 *
 * As in library-bulk.spec.ts, spools are seeded with distinct `used_weight` values so identical
 * never-used spools of one filament do not collapse into a pile row, which has no card and no
 * per-spool checkbox until expanded.
 */

const LIBRARY_MODE_KEY = "spoolman-ng-library-mode";

/** Pins the remembered layout before the page's own script can read it, per test. */
async function setStoredMode(page: Page, mode: "list" | "gallery") {
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    [LIBRARY_MODE_KEY, mode],
  );
}

/** The flat Library narrowed to one location, so the shared instance's other spools stay out. */
async function openAt(page: Page, location: string, extra = "") {
  await page.goto(
    `/?group=none&f=location%3A${encodeURIComponent(location)}${extra}`,
    { waitUntil: "networkidle" },
  );
}

const gridToggle = (page: Page) =>
  page.getByRole("button", { name: "Grid view", exact: true });

async function seedThree(request: Parameters<typeof seedFilament>[0]) {
  const location = unique("GalleryShelf");
  const filament = await seedFilament(request, "Gallery");
  const ids: number[] = [];
  for (let i = 0; i < 3; i++) {
    const res = await request.post("/api/v1/spool", {
      // Distinct used_weight, as in library-bulk.spec.ts: identical never-used spools of one
      // filament collapse into a single pile row instead of three cards.
      data: { filament_id: filament.id, location, used_weight: 10 * (i + 1) },
    });
    expect(res.ok()).toBeTruthy();
    ids.push(((await res.json()) as { id: number }).id);
  }
  return { location, filament, ids };
}

/** A filament of a given material, with its own vendor, for the grouped-view test. */
async function seedFilamentOfMaterial(
  request: Parameters<typeof seedFilament>[0],
  material: string,
) {
  const vendorRes = await request.post("/api/v1/vendor", {
    data: { name: unique(`GalleryVendor-${material}`) },
  });
  expect(vendorRes.ok()).toBeTruthy();
  const vendor = (await vendorRes.json()) as { id: number };
  const name = unique(`Gallery-${material}`);
  const filamentRes = await request.post("/api/v1/filament", {
    data: {
      name,
      vendor_id: vendor.id,
      material,
      color_hex: "3A7BD5",
      price: 22,
      density: 1.24,
      diameter: 1.75,
      weight: 1000,
      spool_weight: 190,
    },
  });
  expect(filamentRes.ok()).toBeTruthy();
  const filament = (await filamentRes.json()) as { id: number; name: string };
  return filament;
}

const bar = (page: Page) => page.getByRole("region", { name: /selected/ });

test("toggling Grid view renders one card per spool, each opening its spool", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedThree(request);
  await setStoredMode(page, "list");
  await openAt(page, location);

  await expect(gridToggle(page)).toHaveAttribute("aria-pressed", "false");
  await expect(gridToggle(page)).toHaveAttribute(
    "title",
    "Browse spools as color tiles",
  );
  await expect(page.locator(".ng-card")).toHaveCount(0);

  await gridToggle(page).click();

  await expect(gridToggle(page)).toHaveAttribute("aria-pressed", "true");
  await expect(gridToggle(page)).toHaveAttribute(
    "title",
    "Back to the full table",
  );
  await expect(page.locator(".ng-card")).toHaveCount(3);
  await expect(page.locator("a.row")).toHaveCount(0);

  for (const id of ids) {
    const card = page.locator(".ng-card", {
      has: page.locator(".id", { hasText: new RegExp(`^#${id}$`) }),
    });
    await expect(card.locator("a.card")).toHaveAttribute(
      "href",
      new RegExp(`sel=spool(%3A|:)${id}(&|$)`),
    ); // The title is clamped to two lines, so the full name has to be reachable on hover.
    const title = card.locator(".title");
    await expect(title).toHaveAttribute(
      "title",
      (await title.textContent())!.trim(),
    );
  }

  const first = page.locator(".ng-card", {
    has: page.locator(".id", { hasText: new RegExp(`^#${ids[0]}$`) }),
  });
  await first.locator("a.card").click();
  await expect(page).toHaveURL(new RegExp(`sel=spool(%3A|:)${ids[0]}`));
});

test("cards share a line instead of stacking one per row", async ({
  page,
  request,
}) => {
  const { location } = await seedThree(request);
  await setStoredMode(page, "gallery");
  await openAt(page, location);

  const cards = page.locator(".ng-card");
  await expect(cards).toHaveCount(3);
  const firstBox = await cards.nth(0).boundingBox();
  const secondBox = await cards.nth(1).boundingBox();
  expect(firstBox).not.toBeNull();
  expect(secondBox).not.toBeNull();
  // Guards against the list container becoming a flex column, which would stack cards
  // vertically instead of letting them wrap as inline blocks.
  expect(firstBox!.y).toBe(secondBox!.y);
});

test("gallery mode survives a reload", async ({ page, request }) => {
  const { location } = await seedThree(request);
  await openAt(page, location);
  // A one-off write, not an addInitScript: that would re-run on the reload below and
  // overwrite the very setting the reload is meant to prove persists.
  await page.evaluate(
    ([key, value]) => window.localStorage.setItem(key, value),
    [LIBRARY_MODE_KEY, "list"] as const,
  );
  await page.reload({ waitUntil: "networkidle" });
  await expect(gridToggle(page)).toHaveAttribute("aria-pressed", "false");

  await gridToggle(page).click();
  await expect(page.locator(".ng-card")).toHaveCount(3);

  await page.reload({ waitUntil: "networkidle" });

  await expect(gridToggle(page)).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".ng-card")).toHaveCount(3);
});

test("grouped by material, cards flow under each material's header", async ({
  page,
  request,
}) => {
  const location = unique("GalleryMatShelf");
  const pla = await seedFilamentOfMaterial(request, "PLA");
  const petg = await seedFilamentOfMaterial(request, "PETG");
  for (const filamentId of [pla.id, petg.id]) {
    const res = await request.post("/api/v1/spool", {
      data: { filament_id: filamentId, location },
    });
    expect(res.ok()).toBeTruthy();
  }
  await setStoredMode(page, "gallery");
  await page.goto(
    `/?group=material&f=location%3A${encodeURIComponent(location)}`,
    { waitUntil: "networkidle" },
  );

  await expect(page.locator(".ng-card")).toHaveCount(2);
  const plaHeader = page.locator(".header", { hasText: "PLA" });
  const petgHeader = page.locator(".header", { hasText: "PETG" });
  await expect(plaHeader).toBeVisible();
  await expect(petgHeader).toBeVisible();

  // A header precedes the cards under it in DOM order: the topmost header sits above the
  // topmost card, never below it.
  const headerBox = await page.locator(".header").first().boundingBox();
  const cardBox = await page.locator(".ng-card").first().boundingBox();
  expect(headerBox).not.toBeNull();
  expect(cardBox).not.toBeNull();
  expect(headerBox!.y).toBeLessThan(cardBox!.y);
});

test("Grid view again restores the row list and removes the cards", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedThree(request);
  await setStoredMode(page, "gallery");
  await openAt(page, location);

  await expect(page.locator(".ng-card")).toHaveCount(3);
  await expect(page.locator("a.row")).toHaveCount(0);

  await gridToggle(page).click();

  await expect(gridToggle(page)).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".ng-card")).toHaveCount(0);
  await expect(page.locator("a.row")).toHaveCount(ids.length);
  for (const id of ids) {
    await expect(
      page.locator("a.row", {
        has: page.locator(".id", { hasText: new RegExp(`^#${id}$`) }),
      }),
    ).toBeVisible();
  }
});

test("Select works on cards, with the checkbox outside the link", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedThree(request);
  await setStoredMode(page, "gallery");
  await openAt(page, location);

  await expect(page.locator(".ng-card")).toHaveCount(3);
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page
    .getByRole("checkbox", { name: `Select spool #${ids[0]}`, exact: true })
    .check();

  await expect(bar(page)).toContainText("1 selected");
  await expect(page.locator("a.card input")).toHaveCount(0);
});
