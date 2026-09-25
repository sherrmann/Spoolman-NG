import { expect, test, type Page } from "@playwright/test";
import { seedFilament, unique } from "./helpers";

/**
 * The SpoolmanDB catalogue fields on a filament (#415 step 1): spool type, finish, pattern,
 * translucent and glow-in-the-dark, shown as five rows in the filament inspector and as five
 * opt-in columns in the flat Library list.
 *
 * See docs/design/filament-parity.md ("Step 1: catalogue fields, and the import fix").
 */

const STORAGE_KEY = "spoolman-ng-library-columns";

async function openInspector(page: Page, filamentId: number) {
  await page.goto(`/?sel=filament:${filamentId}`, { waitUntil: "networkidle" });
  // The article number field sits directly above the catalogue rows; its presence means the
  // inspector has rendered and an absent row below is a real absence rather than an unfinished
  // load.
  await expect(
    page.getByRole("textbox", { name: /Article Number/i }),
  ).toBeVisible();
}

function combo(page: Page, label: string) {
  return page.getByRole("combobox", { name: label, exact: true });
}

async function apiFilament(
  request: Parameters<typeof seedFilament>[0],
  id: number,
) {
  return (await (await request.get(`/api/v1/filament/${id}`)).json()) as {
    spool_type?: string | null;
    finish?: string | null;
    pattern?: string | null;
    translucent?: boolean | null;
    glow?: boolean | null;
  };
}

test("the inspector shows the stored catalogue values, including unset ones as unknown", async ({
  page,
  request,
}) => {
  const filament = await seedFilament(request, "CatShow");
  const res = await request.patch(`/api/v1/filament/${filament.id}`, {
    data: { spool_type: "cardboard", finish: "matte", translucent: false },
  });
  expect(res.ok()).toBeTruthy();

  await openInspector(page, filament.id);

  await expect(combo(page, "Spool Type")).toHaveValue("cardboard");
  await expect(combo(page, "Finish")).toHaveValue("matte");
  // Pattern was never set: unknown, not one of the two named patterns.
  await expect(combo(page, "Pattern")).toHaveValue("");
  // translucent: false is information ("not translucent"), distinct from unknown.
  await expect(combo(page, "Translucent")).toHaveValue("false");
  // glow was never set: unknown.
  await expect(combo(page, "Glow in the Dark")).toHaveValue("");
});

test("changes save, and leave the fields that were not touched as they were", async ({
  page,
  request,
}) => {
  const filament = await seedFilament(request, "CatSave");
  const res = await request.patch(`/api/v1/filament/${filament.id}`, {
    data: { spool_type: "cardboard", translucent: false },
  });
  expect(res.ok()).toBeTruthy();

  await openInspector(page, filament.id);

  // Set Pattern to Sparkle, Glow to Yes, and clear Finish back to unknown: three edits inside
  // one save delay, which reach the server as one patch of the three fields edited.
  await combo(page, "Pattern").selectOption("sparkle");
  await combo(page, "Glow in the Dark").selectOption("true");
  await combo(page, "Finish").selectOption("");

  await expect
    .poll(async () => (await apiFilament(request, filament.id)).pattern)
    .toBe("sparkle");
  expect((await apiFilament(request, filament.id)).glow).toBe(true);
  // Finish was cleared: the API omits a null field from the response rather than sending it as
  // an explicit null.
  expect((await apiFilament(request, filament.id)).finish ?? null).toBeNull();

  // Only the fields edited are sent, so the two that were not keep what they were seeded with.
  const after = await apiFilament(request, filament.id);
  expect(after.translucent).toBe(false);
  expect(after.spool_type).toBe("cardboard");
});

test("a live update between two quick changes does not undo the first", async ({
  page,
  request,
}) => {
  // A spool event carries its filament as the server has it, which replaces the cached one. If
  // it lands between two edits inside the save delay, the first edit must still be saved, not
  // sent back to what the server had.
  const filament = await seedFilament(request, "CatRace");
  const spoolRes = await request.post("/api/v1/spool", {
    data: { filament_id: filament.id, location: unique("CatRace") },
  });
  expect(spoolRes.ok()).toBeTruthy();
  const spoolId = ((await spoolRes.json()) as { id: number }).id;

  // The save delay is a timer; holding the page's clock keeps it from firing until the second
  // edit is made, however long the live event takes to arrive.
  await page.clock.install();
  await openInspector(page, filament.id);
  await combo(page, "Finish").selectOption("matte");
  const patched = await request.patch(`/api/v1/spool/${spoolId}`, {
    data: { comment: "touched" },
  });
  expect(patched.ok()).toBeTruthy();
  // The event has arrived once the cached filament shows the server's unsaved Finish again.
  await expect(combo(page, "Finish")).toHaveValue("");
  await combo(page, "Glow in the Dark").selectOption("true");
  await page.clock.runFor(1000);

  await expect
    .poll(async () => (await apiFilament(request, filament.id)).glow)
    .toBe(true);
  expect((await apiFilament(request, filament.id)).finish).toBe("matte");
});

async function openAt(page: Page, location: string) {
  await page.goto(`/?group=none&f=location%3A${encodeURIComponent(location)}`, {
    waitUntil: "networkidle",
  });
}

async function openColumnsDialog(page: Page) {
  await page.getByRole("button", { name: "Columns", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Columns" });
  await expect(dialog).toBeVisible();
  return dialog;
}

test("a catalogue field shows as a column in the flat library", async ({
  page,
  request,
}) => {
  await page.addInitScript(() => {
    try {
      localStorage.removeItem("spoolman-ng-library-columns");
    } catch {
      /* ignore */
    }
  });

  const filament = await seedFilament(request, "CatCol");
  const patchRes = await request.patch(`/api/v1/filament/${filament.id}`, {
    data: { finish: "glossy" },
  });
  expect(patchRes.ok()).toBeTruthy();

  const location = unique("CatCol");
  const spoolRes = await request.post("/api/v1/spool", {
    data: { filament_id: filament.id, location },
  });
  expect(spoolRes.ok()).toBeTruthy();

  await openAt(page, location);

  const dialog = await openColumnsDialog(page);
  await dialog.getByRole("checkbox", { name: "Finish", exact: true }).check();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Columns" })).toHaveCount(0);

  await expect(page.locator(".hcell[data-col='finish']")).toBeVisible();
  await expect(page.locator("a.cells .cell[data-col='finish']")).toHaveText(
    "Glossy",
  );

  expect(
    await page.evaluate((k) => localStorage.getItem(k), STORAGE_KEY),
  ).not.toBeNull();
});

test("a filament imported from SpoolmanDB keeps its catalogue fields", async ({
  page,
  request,
}) => {
  // CI has no SpoolmanDB of its own (the catalogue is fetched from the internet), so the search
  // is answered here with one entry. Everything after it is real: picking the entry makes the
  // client create the filament through the API, which is the request that used to leave these
  // five fields out.
  const extId = unique("catalogue_entry").toLowerCase();
  const name = unique("Imported");
  await page.route("**/api/v1/external/filament/search**", (route) =>
    route.fulfill({
      contentType: "application/json",
      headers: { "x-total-count": "1" },
      body: JSON.stringify([
        {
          id: extId,
          manufacturer: unique("CatVendor"),
          name,
          material: "PLA",
          density: 1.24,
          weight: 1000,
          spool_weight: 200,
          diameter: 1.75,
          color_hex: "cc3300",
          spool_type: "metal",
          finish: "glossy",
          pattern: "marble",
          translucent: true,
          glow: false,
        },
      ]),
    }),
  );

  await page.goto("/", { waitUntil: "networkidle" });
  await page
    .locator("header")
    .getByRole("button", { name: "Add spools" })
    .filter({ visible: true })
    .first()
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.locator("input.search-big").fill(name);
  await dialog.getByRole("button").filter({ hasText: name }).first().click();
  await dialog.getByPlaceholder("e.g. Shelf A").fill(unique("CatImport"));
  await dialog
    .getByRole("button", { name: "Add 1 spool", exact: true })
    .click();
  await expect(dialog).toBeHidden();

  const res = await request.get("/api/v1/filament", {
    params: { external_id: extId },
  });
  expect(res.ok()).toBeTruthy();
  const created = (await res.json()) as Array<Record<string, unknown>>;
  expect(created).toHaveLength(1);
  expect(created[0]).toMatchObject({
    spool_type: "metal",
    finish: "glossy",
    pattern: "marble",
    translucent: true,
    glow: false,
  });
});
