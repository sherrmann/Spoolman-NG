import { expect, test, type Page } from "@playwright/test";
import { seedFilament, unique } from "./helpers";

/**
 * Choosing, reordering, resizing and hiding the flat Library list's columns (#412 step 5).
 *
 * Until the user opens the manager and changes something, the flat list is upstream's own row
 * (`a.row`) and there is no stored configuration: this fork's cell renderer (`a.cells`, one
 * `span.cell` per visible column) and header (`div.ng-col-header`) only take over once a change
 * has been made, and "Reset columns" hands the list straight back to upstream's row. Grouped
 * views and the gallery ignore columns entirely -- no "Columns" button, and upstream's rows even
 * with a stored configuration, since a row there belongs to a different context.
 */

const STORAGE_KEY = "spoolman-ng-library-columns";

function clearColumnsOnLoad(page: Page) {
  return page.addInitScript(() => {
    try {
      localStorage.removeItem("spoolman-ng-library-columns");
    } catch {
      /* ignore */
    }
  });
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

async function seedOneSpool(
  request: Parameters<typeof seedFilament>[0],
  prefix: string,
  extra: Record<string, unknown> = {},
) {
  const location = unique(prefix);
  const filament = await seedFilament(request, prefix);
  const res = await request.post("/api/v1/spool", {
    data: { filament_id: filament.id, location, ...extra },
  });
  expect(res.ok()).toBeTruthy();
  const id = ((await res.json()) as { id: number }).id;
  return { location, filamentId: filament.id, spoolId: id };
}

async function openColumnsDialog(page: Page) {
  await page.getByRole("button", { name: "Columns", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Columns" });
  await expect(dialog).toBeVisible();
  return dialog;
}

/** Closes the columns panel via its own close button (Escape has a test of its own). */
async function closeColumnsDialog(page: Page) {
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Columns" })).toHaveCount(0);
}

function storedConfig(page: Page) {
  return page.evaluate(() =>
    localStorage.getItem("spoolman-ng-library-columns"),
  );
}

test("default: no header, upstream rows, nothing stored", async ({
  page,
  request,
}) => {
  await clearColumnsOnLoad(page);
  const { location } = await seedOneSpool(request, "ColDefault");
  await openAt(page, location);

  await expect(page.locator("a.row")).toHaveCount(1);
  await expect(page.locator("a.cells")).toHaveCount(0);
  await expect(page.locator(".ng-col-header")).toHaveCount(0);
  expect(await storedConfig(page)).toBeNull();
});

test("the columns panel takes focus when opened and gives it back to its button on Escape", async ({
  page,
  request,
}) => {
  await clearColumnsOnLoad(page);
  const { location } = await seedOneSpool(request, "ColFocus");
  await openAt(page, location);

  const dialog = await openColumnsDialog(page);
  await expect
    .poll(() => dialog.evaluate((d) => d.contains(document.activeElement)))
    .toBe(true);

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Columns", exact: true }),
  ).toBeFocused();
});

test("showing a column switches the list to the fork's cell row", async ({
  page,
  request,
}) => {
  await clearColumnsOnLoad(page);
  const lotNr = unique("LOT");
  const { location } = await seedOneSpool(request, "ColShow", {
    lot_nr: lotNr,
  });
  await openAt(page, location);

  const dialog = await openColumnsDialog(page);
  await dialog.getByRole("checkbox", { name: "Lot Nr", exact: true }).check();

  await closeColumnsDialog(page);

  await expect(page.locator(".ng-col-header")).toBeVisible();
  await expect(
    page.locator(".ng-col-header .hcell[data-col='lot']"),
  ).toBeVisible();
  await expect(page.locator("a.row")).toHaveCount(0);
  const row = page.locator("a.cells");
  await expect(row).toHaveCount(1);
  await expect(row.locator(".cell[data-col='lot']")).toHaveText(lotNr);
  expect(await storedConfig(page)).not.toBeNull();
});

test("hiding a column removes its header and row cell", async ({
  page,
  request,
}) => {
  await clearColumnsOnLoad(page);
  const { location } = await seedOneSpool(request, "ColHide");
  await openAt(page, location);

  // Location is shown by default once columns are on (it is one of upstream's starting six),
  // so toggling any other column on first turns the fork's row on with Location still visible.
  const dialog = await openColumnsDialog(page);
  await dialog.getByRole("checkbox", { name: "Lot Nr", exact: true }).check();
  await expect(page.locator(".hcell[data-col='location']")).toHaveCount(1);

  await dialog
    .getByRole("checkbox", { name: "Location", exact: true })
    .uncheck();
  await closeColumnsDialog(page);

  await expect(
    page.locator(".ng-col-header .hcell[data-col='location']"),
  ).toHaveCount(0);
  await expect(page.locator("a.cells .cell[data-col='location']")).toHaveCount(
    0,
  );
});

test("reordering a column survives a reload", async ({ page, request }) => {
  const { location } = await seedOneSpool(request, "ColReorder");
  await openAt(page, location);
  // A one-off clear, not an init script: this test reloads, and an init script would re-run on
  // that reload and wipe the very configuration the reload is meant to prove survives.
  await page.evaluate(() =>
    localStorage.removeItem("spoolman-ng-library-columns"),
  );

  const dialog = await openColumnsDialog(page);
  await dialog.getByRole("checkbox", { name: "Lot Nr", exact: true }).check();

  // Before moving: Location follows Remaining Weight (upstream's starting order is
  // id, swatch, name, progress, remaining, location).
  const hcells = () => page.locator(".ng-col-header .hcell");
  const idsBefore = await hcells().evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-col")),
  );
  expect(idsBefore.indexOf("location")).toBe(
    idsBefore.indexOf("remaining") + 1,
  );

  await dialog.getByRole("button", { name: "Move Location up" }).click();
  await closeColumnsDialog(page);

  const idsAfter = await hcells().evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-col")),
  );
  // location and remaining swapped one place: location now precedes remaining, taking the slot
  // remaining used to hold.
  expect(idsAfter.indexOf("location")).toBe(idsAfter.indexOf("remaining") - 1);
  expect(idsAfter.indexOf("location")).toBe(idsBefore.indexOf("remaining"));
  expect(idsAfter.indexOf("location")).toBeLessThan(
    idsBefore.indexOf("location"),
  );

  await page.reload({ waitUntil: "networkidle" });
  const idsReloaded = await hcells().evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-col")),
  );
  expect(idsReloaded).toEqual(idsAfter);
});

test("resizing a column with the keyboard widens both header and row cell, and survives a reload", async ({
  page,
  request,
}) => {
  const lotNr = unique("LOT");
  const { location } = await seedOneSpool(request, "ColResize", {
    lot_nr: lotNr,
  });
  await openAt(page, location);
  // A one-off clear, not an init script: this test reloads (see the reorder test above).
  await page.evaluate(() =>
    localStorage.removeItem("spoolman-ng-library-columns"),
  );

  const dialog = await openColumnsDialog(page);
  await dialog.getByRole("checkbox", { name: "Lot Nr", exact: true }).check();
  await closeColumnsDialog(page);

  const lotHandle = page.getByRole("separator", { name: "Resize Lot Nr" });
  const lotHcell = page.locator(".hcell[data-col='lot']");
  const lotCell = page.locator("a.cells .cell[data-col='lot']");

  const widthBefore = (await lotHcell.boundingBox())!.width;

  // With Lot Nr shown the columns are wider than the pane, so its handle starts partly
  // off-screen. Focusing it (what Tab does) makes the browser scroll the header to it; the list
  // has to follow, or the header and the cells below it stop lining up.
  const list = page.locator(".ng-col-header ~ .groups");
  expect(
    await list.evaluate((el) => el.scrollWidth > el.clientWidth),
    "the columns must overflow the pane for this check to mean anything",
  ).toBe(true);
  await lotHandle.focus();
  await expect
    .poll(() => list.evaluate((el) => el.scrollLeft))
    .toBeGreaterThan(0);
  await expect
    .poll(async () => {
      const h = (await lotHcell.boundingBox())!.x;
      const c = (await lotCell.boundingBox())!.x;
      return Math.round(h - c);
    })
    .toBe(0);

  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");

  const hcellBoxAfter = (await lotHcell.boundingBox())!;
  const cellBoxAfter = (await lotCell.boundingBox())!;
  expect(hcellBoxAfter.width).toBeGreaterThanOrEqual(widthBefore + 19);
  expect(hcellBoxAfter.width).toBeLessThanOrEqual(widthBefore + 21);
  expect(cellBoxAfter.width).toBeGreaterThanOrEqual(hcellBoxAfter.width - 1);
  expect(cellBoxAfter.width).toBeLessThanOrEqual(hcellBoxAfter.width + 1);
  expect(cellBoxAfter.x).toBeGreaterThanOrEqual(hcellBoxAfter.x - 1);
  expect(cellBoxAfter.x).toBeLessThanOrEqual(hcellBoxAfter.x + 1);

  await page.reload({ waitUntil: "networkidle" });
  const hcellBoxReloaded = (await page
    .locator(".hcell[data-col='lot']")
    .boundingBox())!;
  expect(hcellBoxReloaded.width).toBeGreaterThanOrEqual(
    hcellBoxAfter.width - 1,
  );
  expect(hcellBoxReloaded.width).toBeLessThanOrEqual(hcellBoxAfter.width + 1);
});

test("nudging the name column narrower lowers its minimum, not raises it to the drawn width", async ({
  page,
  request,
}) => {
  await clearColumnsOnLoad(page);
  const { location } = await seedOneSpool(request, "ColName");
  await openAt(page, location);
  const dialog = await openColumnsDialog(page);
  await dialog
    .getByRole("checkbox", { name: "Location", exact: true })
    .uncheck();
  await closeColumnsDialog(page);

  // The name takes the space left over, so it is drawn far wider than its 100 px minimum.
  const handle = page.getByRole("separator", { name: /^Resize Name/ });
  expect(
    (await page.locator(".hcell[data-col='name']").boundingBox())!.width,
  ).toBeGreaterThan(150);
  await expect(handle).toHaveAttribute("aria-valuenow", "100");

  await handle.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(handle).toHaveAttribute("aria-valuenow", "90");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(handle).toHaveAttribute("aria-valuenow", "110");
});

test("a change made before the extra fields have loaded does not lose a shown extra-field column", async ({
  page,
  request,
}) => {
  const key = unique("earlyfield")
    .toLowerCase()
    .replace(/[^a-z0-9_]/g, "_");
  const fieldName = unique("Early");
  const fieldRes = await request.post(`/api/v1/field/spool/${key}`, {
    data: { name: fieldName, field_type: "text" },
  });
  expect(fieldRes.ok()).toBeTruthy();

  try {
    const { location } = await seedOneSpool(request, "ColEarly");
    await openAt(page, location);
    await page.evaluate(() =>
      localStorage.removeItem("spoolman-ng-library-columns"),
    );
    const dialog = await openColumnsDialog(page);
    await dialog
      .getByRole("checkbox", { name: fieldName, exact: true })
      .check();
    await closeColumnsDialog(page);
    const extraHeader = page.locator(`.hcell[data-col='extra.${key}']`);
    await expect(extraHeader).toBeVisible();

    // Hold the field definitions back on the next load, and change a column meanwhile.
    let release!: () => void;
    const released = new Promise<void>((r) => (release = r));
    await page.route("**/api/v1/field/spool", async (route) => {
      await released;
      await route.continue();
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    const idHandle = page.getByRole("separator", { name: "Resize ID" });
    await idHandle.focus();
    await page.keyboard.press("ArrowRight");
    const panel = await openColumnsDialog(page);
    await expect(
      panel.getByRole("checkbox", { name: "Lot Nr", exact: true }),
    ).toBeDisabled();
    await closeColumnsDialog(page);

    release();
    await expect(extraHeader).toBeVisible();
    const stored = JSON.parse((await storedConfig(page))!) as {
      order: string[];
      hidden: string[];
    };
    expect(stored.order).toContain(`extra.${key}`);
    expect(stored.hidden).not.toContain(`extra.${key}`);
  } finally {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await request.delete(`/api/v1/field/spool/${key}`);
  }
});

test("a spool extra field's column shows its stored value", async ({
  page,
  request,
}) => {
  await clearColumnsOnLoad(page);
  const key = unique("premiumfield")
    .toLowerCase()
    .replace(/[^a-z0-9_]/g, "_");
  const fieldName = unique("Premium");

  const fieldRes = await request.post(`/api/v1/field/spool/${key}`, {
    data: { name: fieldName, field_type: "text" },
  });
  expect(fieldRes.ok()).toBeTruthy();

  try {
    const filament = await seedFilament(request, "ColExtra");
    const location = unique("ColExtra");
    const spoolRes = await request.post("/api/v1/spool", {
      data: {
        filament_id: filament.id,
        location,
        extra: { [key]: JSON.stringify("Premium") },
      },
    });
    expect(spoolRes.ok()).toBeTruthy();

    await openAt(page, location);
    const dialog = await openColumnsDialog(page);
    await dialog
      .getByRole("checkbox", { name: fieldName, exact: true })
      .check();
    await closeColumnsDialog(page);

    await expect(page.locator(`.hcell[data-col='extra.${key}']`)).toBeVisible();
    await expect(
      page.locator(`a.cells .cell[data-col='extra.${key}']`),
    ).toHaveText("Premium");
  } finally {
    await request.delete(`/api/v1/field/spool/${key}`);
  }
});

test("reset brings back upstream's row and forgets the configuration", async ({
  page,
  request,
}) => {
  await clearColumnsOnLoad(page);
  const { location } = await seedOneSpool(request, "ColReset");
  await openAt(page, location);

  const dialog = await openColumnsDialog(page);
  await dialog.getByRole("checkbox", { name: "Lot Nr", exact: true }).check();
  await expect(
    dialog.getByRole("button", { name: "Reset columns" }),
  ).toBeEnabled();

  await dialog.getByRole("button", { name: "Reset columns" }).click();

  await expect(page.locator(".ng-col-header")).toHaveCount(0);
  await expect(page.locator("a.row")).toHaveCount(1);
  await expect(page.locator("a.cells")).toHaveCount(0);
  expect(await storedConfig(page)).toBeNull();
});

test("grouped by filament, columns are ignored even with a stored configuration", async ({
  page,
  request,
}) => {
  await clearColumnsOnLoad(page);
  const { location } = await seedOneSpool(request, "ColGrouped");
  await openAt(page, location);

  const dialog = await openColumnsDialog(page);
  await dialog.getByRole("checkbox", { name: "Lot Nr", exact: true }).check();
  await closeColumnsDialog(page);
  expect(await storedConfig(page)).not.toBeNull();

  await page.goto(
    `/?group=filament&f=location%3A${encodeURIComponent(location)}`,
    {
      waitUntil: "networkidle",
    },
  );

  await expect(
    page.getByRole("button", { name: "Columns", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator("a.row")).toHaveCount(1);
  await expect(page.locator("a.cells")).toHaveCount(0);
  await expect(page.locator(".ng-col-header")).toHaveCount(0);
});
