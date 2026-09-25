import { expect, test, type Page } from "@playwright/test";
import { unique } from "./helpers";

/**
 * The totals line under the Library list (#412 step 4): what the spools on screen, or the
 * current selection, add up to.
 *
 * Numbers are hand-computed here from what was seeded, never taken from the app's own sums, so
 * a broken total (wrong source list, wrong weightAuto rounding, wrong price fallback) actually
 * fails a test.
 */

async function post(request: any, path: string, data: unknown) {
  const res = await request.post(`/api/v1${path}`, { data });
  expect(res.ok()).toBeTruthy();
  return res.json();
}

/**
 * Three spools at one unique location:
 *  - filament A (price 20): spool used 250, and spool used 100 with its own price 25
 *  - filament B (no price): spool used 600
 *
 * Distinct used_weight values throughout so no two never-used spools of one filament could ever
 * collapse into a single grouped-view pile (none of these are never-used anyway).
 *
 * remaining = 750 + 900 + 400 = 2050 g -> "2 kg" (floor to one decimal, trailing .0 dropped)
 * used = 250 + 100 + 600 = 950 g -> "950 g"
 * price = 20 (A's own, from filament) + 25 (spool's own) = 45.00; B has no price anywhere, so
 * it is left out of the sum entirely (not counted as 0).
 */
async function seedThree(request: any) {
  const location = unique("TotalsShelf");
  const vendor = await post(request, "/vendor", {
    name: unique("TotalsVendor"),
  });
  const filamentA = await post(request, "/filament", {
    name: unique("TotalsA"),
    vendor_id: vendor.id,
    material: "PLA",
    density: 1.24,
    diameter: 1.75,
    weight: 1000,
    price: 20,
  });
  const filamentB = await post(request, "/filament", {
    name: unique("TotalsB"),
    vendor_id: vendor.id,
    material: "PLA",
    density: 1.24,
    diameter: 1.75,
    weight: 1000,
  });

  const spoolA1 = await post(request, "/spool", {
    filament_id: filamentA.id,
    location,
    used_weight: 250,
  });
  const spoolA2 = await post(request, "/spool", {
    filament_id: filamentA.id,
    location,
    used_weight: 100,
    price: 25,
  });
  const spoolB1 = await post(request, "/spool", {
    filament_id: filamentB.id,
    location,
    used_weight: 600,
  });

  return {
    location,
    filamentAId: filamentA.id,
    filamentBId: filamentB.id,
    // used_weight indexed the same way, for computing "whichever row is first"'s expectation.
    spools: {
      [spoolA1.id]: { used: 250, remaining: 750, price: 20 },
      [spoolA2.id]: { used: 100, remaining: 900, price: 25 },
      [spoolB1.id]: { used: 600, remaining: 400, price: null as number | null },
    } as Record<
      number,
      { used: number; remaining: number; price: number | null }
    >,
    ids: [spoolA1.id, spoolA2.id, spoolB1.id] as number[],
  };
}

/** The flat Library narrowed to one location, so the shared instance's other spools stay out. */
async function openAt(page: Page, location: string, extra = "") {
  await page.goto(
    `/?group=none&f=location%3A${encodeURIComponent(location)}${extra}`,
    {
      waitUntil: "networkidle",
    },
  );
}

const bar = (page: Page) => page.getByRole("region", { name: /selected/ });
const totals = (page: Page) => page.locator(".totals[role=status]");

/** The line's text with runs of whitespace collapsed to one space, for robust comparison. */
async function totalsText(page: Page) {
  const raw = await totals(page).innerText();
  return raw.replace(/\s+/g, " ").trim();
}

test("shown totals: three spools, mixed prices, weight rolled to kg", async ({
  page,
  request,
}) => {
  const { location } = await seedThree(request);
  await openAt(page, location);

  const text = await totalsText(page);
  expect(text).toMatch(/^3 spools shown\b/);
  expect(text).toContain("Remaining Weight 2 kg");
  expect(text).toContain("Used Weight 950 g");
  // Price formatting comes from server currency settings; assert on the number, not the symbol.
  expect(text).toMatch(/Price\s*.?45[.,]00/);
});

test("selecting one spool switches the totals to just that spool, clearing restores the page total", async ({
  page,
  request,
}) => {
  const { location, ids, spools } = await seedThree(request);
  const targetId = ids[1]; // spool A2: used 100, remaining 900, own price 25
  const expected = spools[targetId];
  await openAt(page, location);

  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page
    .getByRole("checkbox", { name: `Select spool #${targetId}`, exact: true })
    .check();
  await expect(bar(page)).toContainText("1 selected");

  const selectedText = await totalsText(page);
  expect(selectedText).toMatch(/^1 spool selected\b/);
  expect(selectedText).toContain(`Remaining Weight ${expected.remaining} g`);
  expect(selectedText).toContain(`Used Weight ${expected.used} g`);
  expect(selectedText).toMatch(
    new RegExp(`Price\\s*.?${expected.price}[.,]00`),
  );

  await bar(page).getByRole("button", { name: "Clear selection" }).click();
  await expect(bar(page)).toHaveCount(0);

  const shownText = await totalsText(page);
  expect(shownText).toMatch(/^3 spools shown\b/);
  expect(shownText).toContain("Remaining Weight 2 kg");
  expect(shownText).toContain("Used Weight 950 g");
});

test("page size 1 shows only the first row's own numbers", async ({
  page,
  request,
}) => {
  const { location, spools } = await seedThree(request);
  await openAt(page, location, "&size=1");

  // Find which spool actually landed on this single-row page, from the row's own id label --
  // the sort order is not asserted here, only that the totals match whichever row is shown.
  const idText = await page.locator("a.row .id").first().innerText();
  const match = idText.trim().match(/^#(\d+)$/);
  expect(match).not.toBeNull();
  const shownId = Number(match![1]);
  const expected = spools[shownId];
  expect(expected).toBeDefined();

  await expect(page.locator("a.row")).toHaveCount(1);

  const text = await totalsText(page);
  expect(text).toMatch(/^1 spool shown\b/);
  expect(text).toContain(`Remaining Weight ${expected.remaining} g`);
  expect(text).toContain(`Used Weight ${expected.used} g`);
  if (expected.price !== null) {
    expect(text).toMatch(new RegExp(`Price\\s*.?${expected.price}[.,]00`));
  } else {
    expect(text).not.toContain("Price");
  }
});

test("no priced spool in view leaves the Price part off the line entirely", async ({
  page,
  request,
}) => {
  const location = unique("TotalsNoPrice");
  const vendor = await post(request, "/vendor", {
    name: unique("TotalsNoPriceVendor"),
  });
  const filament = await post(request, "/filament", {
    name: unique("TotalsNoPriceF"),
    vendor_id: vendor.id,
    material: "PLA",
    density: 1.24,
    diameter: 1.75,
    weight: 1000,
  });
  await post(request, "/spool", {
    filament_id: filament.id,
    location,
    used_weight: 300,
  });
  await post(request, "/spool", {
    filament_id: filament.id,
    location,
    used_weight: 700,
  });

  await openAt(page, location);

  const text = await totalsText(page);
  expect(text).toMatch(/^2 spools shown\b/);
  expect(text).not.toContain("Price");
});

test("a selected spool on another page is totalled as it stands now, not as it was ticked", async ({
  page,
  request,
}) => {
  // Its row is not re-rendered while another page is showing, so the snapshot taken when it
  // was ticked goes stale; the totals must follow the live update instead.
  const { location, spools } = await seedThree(request);
  await openAt(page, location, "&size=1");
  await page.getByRole("button", { name: "Select", exact: true }).click();
  const box = page.getByRole("checkbox", { name: /Select spool #\d+/ }).first();
  const id = Number(
    (await box.getAttribute("aria-label"))!.match(/#(\d+)/)![1],
  );
  await box.check();
  await expect(totals(page)).toContainText("1 spool selected");

  // Page 2, in the app, so the selection survives.
  await page.getByRole("link", { name: "2", exact: true }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(
    page.getByRole("checkbox", { name: `Select spool #${id}`, exact: true }),
  ).toHaveCount(0);

  const res = await request.patch(`/api/v1/spool/${id}`, {
    data: { used_weight: 500 },
  });
  expect(res.ok()).toBeTruthy();

  // Initial 1000 g each: 500 used leaves 500.
  await expect
    .poll(async () => totalsText(page))
    .toContain("Used Weight 500 g");
  expect(await totalsText(page)).toContain("Remaining Weight 500 g");
  expect(spools[id]).toBeDefined();
});
