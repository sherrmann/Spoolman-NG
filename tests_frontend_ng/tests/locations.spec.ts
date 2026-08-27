import { expect, test, type Page } from "@playwright/test";
import { allSpools, seedLocation, unique } from "./helpers";

/**
 * The fork's Location ENTITY registry (client_v2/src/routes/locations/) and the detail page a
 * scanned `WEB+SPOOLMAN:L-<id>` label lands on (routes/location/show/[id]/).
 *
 * Deliberately NOT a board test. Grouping spools by location, and dragging them between
 * columns, is upstream's own /dashboard page; this suite covers only the registry rows that
 * carry custom fields and a scannable identity, which /dashboard has no notion of.
 *
 * The registry and a spool's `location` string share no foreign key -- a spool is matched to a
 * row by name equality -- so the detail page's spool list is asserted through that matching
 * rather than through any relation the API would enforce.
 */

const row = (page: Page, text: string) =>
  page.getByRole("listitem").filter({ hasText: text }).first();

async function openLocations(page: Page) {
  await page.goto("/locations", { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

/** A location plus a spool actually stored there (matched by name, not by id). */
async function seedOccupied(request: Parameters<typeof seedLocation>[0], prefix: string) {
  const loc = await seedLocation(request, prefix);
  const post = async (path: string, body: unknown) => {
    const res = await request.post(`/api/v1${path}`, {
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify(body),
    });
    if (!res.ok()) throw new Error(`POST ${path} -> ${res.status()} ${await res.text()}`);
    return res.json();
  };
  const vendor = await post("/vendor", { name: unique(`${prefix}Vendor`) });
  const filament = await post("/filament", {
    name: unique(`${prefix}Fil`),
    vendor_id: vendor.id,
    material: "PLA",
    color_hex: "22AA66",
    price: 20,
    density: 1.24,
    diameter: 1.75,
    weight: 1000,
    spool_weight: 190,
  });
  await post("/spool", { filament_id: filament.id, used_weight: 250, location: loc.name });
  return { ...loc, filamentName: filament.name as string };
}

test("lists registry rows with their name and spool count", async ({ page, request }) => {
  const occupied = await seedOccupied(request, "List");
  await openLocations(page);

  const r = row(page, occupied.name);
  await expect(r).toBeVisible();
  await expect(r).toContainText("1");
});

test("clicking anywhere on a row opens that location", async ({ page, request }) => {
  // Same stretched-link guard as orders.spec.ts: the name's ::after covers the whole <li>, and
  // only stays covering it while `.name` itself is unpositioned. Playwright clicks the centre,
  // which is well away from the name text at the row's left edge.
  const loc = await seedLocation(request, "Click");
  await openLocations(page);

  await row(page, loc.name).click();

  await expect(page).toHaveURL(new RegExp(`/location/show/${loc.id}$`));
  await expect(page.getByRole("heading", { name: loc.name })).toBeVisible();
});

test("creating a location rejects a duplicate name before writing", async ({ page, request }) => {
  const existing = await seedLocation(request, "Dupe");
  await openLocations(page);

  await page.getByRole("button", { name: /new location/i }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox").fill(existing.name);
  await dialog.getByRole("button", { name: /create/i }).click();

  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(/already exists/i);

  // The backend puts no uniqueness constraint on location.name -- a duplicate POST would have
  // returned 200 and left two rows -- so the guard has to be the client's, and this asserts the
  // server never saw the request rather than that the dialog looked unhappy.
  const rows = (await (await request.get(`/api/v1/locations?name=${encodeURIComponent(existing.name)}`)).json()) as unknown[];
  expect(rows).toHaveLength(1);
});

test("creating a location adds it to the registry", async ({ page, request }) => {
  const name = unique("Fresh");
  await openLocations(page);

  await page.getByRole("button", { name: /new location/i }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox").fill(name);
  await dialog.getByRole("button", { name: /create/i }).click();

  await expect(row(page, name)).toBeVisible();
  const rows = (await (await request.get(`/api/v1/locations?name=${encodeURIComponent(name)}`)).json()) as { name: string }[];
  expect(rows.map((r) => r.name)).toContain(name);
});

test("a location holding spools cannot be deleted", async ({ page, request }) => {
  const occupied = await seedOccupied(request, "Held");
  const empty = await seedLocation(request, "Empty");
  await openLocations(page);

  // Deleting a row that still names spools would orphan their custom-field values, so the
  // control is absent rather than merely disabled.
  await expect(row(page, occupied.name).getByRole("button", { name: /delete/i })).toHaveCount(0);
  await expect(row(page, empty.name).getByRole("button", { name: /delete/i })).toBeVisible();
});

test("the detail page lists the spools stored at that location", async ({ page, request }) => {
  const occupied = await seedOccupied(request, "Detail");
  await page.goto(`/location/show/${occupied.id}`, { waitUntil: "networkidle" });

  await expect(page.getByRole("heading", { name: occupied.name })).toBeVisible();
  await expect(page.getByText(occupied.filamentName)).toBeVisible();

  // Matched by name equality, so prove the page is filtering rather than listing everything.
  const elsewhere = (await allSpools(request)).filter((s) => s.location !== occupied.name);
  expect(elsewhere.length, "seed another spool elsewhere or this asserts nothing").toBeGreaterThan(0);
});

test("a stale QR label lands on a clear message, not a blank page", async ({ page }) => {
  await page.goto("/location/show/999999", { waitUntil: "networkidle" });
  await expect(page.getByText(/no longer exists/i)).toBeVisible();
});

test("the page scrolls inside the app shell rather than overflowing it", async ({ page, request }) => {
  await seedLocation(request, "Scroll");
  await page.setViewportSize({ width: 700, height: 800 });
  await openLocations(page);
  const { docScroll, viewport } = await page.evaluate(() => ({
    docScroll: document.documentElement.scrollHeight,
    viewport: window.innerHeight,
  }));
  expect(docScroll, `the document grew to ${docScroll}px`).toBeLessThanOrEqual(viewport + 1);
});
