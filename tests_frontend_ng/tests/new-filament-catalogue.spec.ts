import { expect, test, type Locator, type Page } from "@playwright/test";
import { seedFilament, unique } from "./helpers";

/**
 * The SpoolmanDB catalogue fields (spool type, finish, pattern, translucent, glow-in-the-dark)
 * on the new-filament form, not just the filament inspector.
 *
 * `NewFilamentCatalogueFields.svelte` mounts inside `NewFilamentCards`' collapsed "Advanced
 * specs" block, wherever that card is used — here, the Add Spools dialog's step 2. A blank form
 * starts with all five unknown; a duplicate starts from the source filament's values; either
 * way, whatever the five selects hold when Add is pressed is what the created filament gets.
 */

async function openAddSpoolModal(page: Page): Promise<Locator> {
  await page
    .locator("header")
    .getByRole("button", { name: "Add spools" })
    .filter({ visible: true })
    .first()
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  return dialog;
}

/**
 * Locate a numeric input by its field label, the same way as `numberField` in
 * tests_frontend_v2/tests/helpers.ts: NumberInput's <label> also wraps stepper furniture and a
 * help toggle, so getByLabel can't match it exactly.
 */
function numberField(container: Locator, label: string): Locator {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return container
    .locator("label")
    .filter({ hasText: new RegExp(`^\\s*${escaped}\\b`) })
    .first()
    .locator("input")
    .first();
}

/** One of the five catalogue selects, named exactly as the filament inspector's own rows. */
function combo(container: Locator, label: string): Locator {
  return container.getByRole("combobox", { name: label, exact: true });
}

async function apiFilament(page: Page, id: number) {
  const res = await page.request.get(`/api/v1/filament/${id}`);
  return (await res.json()) as {
    spool_type?: string | null;
    finish?: string | null;
    pattern?: string | null;
    translucent?: boolean | null;
    glow?: boolean | null;
  };
}

/**
 * Fill in the fields a new filament needs before Add will accept it: name, material and — under
 * Advanced specs, which this form opens for the caller — density. Material is set to a name
 * COMMON_MATERIALS auto-fills density for, but density is still typed explicitly so the test
 * does not depend on that lookup succeeding.
 */
async function fillRequiredFields(dialog: Locator, name: string) {
  await dialog.getByPlaceholder("e.g. PolyTerra Matte Sage").fill(name);
  await dialog.getByPlaceholder("PLA", { exact: true }).fill("PLA");
  await dialog.getByRole("button", { name: /^Advanced specs/ }).click();
  await numberField(dialog, "Density").fill("1.24");
}

test("creating a new filament sends the chosen catalogue values", async ({
  page,
}) => {
  const name = unique("NewFilCat");

  await page.goto("/", { waitUntil: "networkidle" });
  const dialog = await openAddSpoolModal(page);
  await dialog.getByRole("button", { name: /^Create a new filament/ }).click();
  await fillRequiredFields(dialog, name);

  await combo(dialog, "Spool Type").selectOption("cardboard");
  await combo(dialog, "Finish").selectOption("matte");
  await combo(dialog, "Translucent").selectOption("false");
  // Pattern and Glow are left on their unknown default.

  const [response] = await Promise.all([
    page.waitForResponse(
      (res) =>
        res.url().includes("/api/v1/filament") &&
        res.request().method() === "POST",
    ),
    dialog.getByRole("button", { name: "Add 1 spool", exact: true }).click(),
  ]);
  await expect(dialog).toBeHidden();

  const created = (await response.json()) as { id: number };
  const filament = await apiFilament(page, created.id);
  expect(filament.spool_type).toBe("cardboard");
  expect(filament.finish).toBe("matte");
  expect(filament.translucent).toBe(false);
  expect(filament.glow ?? null).toBeNull();
  expect(filament.pattern ?? null).toBeNull();
});

test("duplicating a filament pre-fills and carries forward its catalogue fields", async ({
  page,
  request,
}) => {
  const source = await seedFilament(request, "CatDupSource");
  const patchRes = await request.patch(`/api/v1/filament/${source.id}`, {
    data: {
      spool_type: "metal",
      finish: "glossy",
      translucent: true,
      glow: false,
    },
  });
  expect(patchRes.ok()).toBeTruthy();

  // The inspector's "Duplicate" button opens the Add Spools dialog straight at step 2, with
  // Advanced specs already open — it is what makes the copy visibly a copy.
  await page.goto(`/?sel=filament:${source.id}`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Duplicate", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  await expect(combo(dialog, "Spool Type")).toHaveValue("metal");
  await expect(combo(dialog, "Finish")).toHaveValue("glossy");
  // Pattern was never set on the source: unknown, pre-filled as such.
  await expect(combo(dialog, "Pattern")).toHaveValue("");
  await expect(combo(dialog, "Translucent")).toHaveValue("true");
  await expect(combo(dialog, "Glow in the Dark")).toHaveValue("false");

  const copyName = unique("CatDupCopy");
  await dialog.getByPlaceholder("e.g. PolyTerra Matte Sage").fill(copyName);

  const [response] = await Promise.all([
    page.waitForResponse(
      (res) =>
        res.url().includes("/api/v1/filament") &&
        res.request().method() === "POST",
    ),
    dialog.getByRole("button", { name: "Add 1 spool", exact: true }).click(),
  ]);
  await expect(dialog).toBeHidden();

  const created = (await response.json()) as { id: number };
  const filament = await apiFilament(page, created.id);
  expect(filament.spool_type).toBe("metal");
  expect(filament.finish).toBe("glossy");
  expect(filament.translucent).toBe(true);
  expect(filament.glow).toBe(false);
  expect(filament.pattern ?? null).toBeNull();
});

test("a blank new filament is created with all five catalogue fields null", async ({
  page,
}) => {
  const name = unique("NewFilBlank");

  await page.goto("/", { waitUntil: "networkidle" });
  const dialog = await openAddSpoolModal(page);
  await dialog.getByRole("button", { name: /^Create a new filament/ }).click();
  await fillRequiredFields(dialog, name);
  // Advanced specs is open (fillRequiredFields opened it for the density field), but none of
  // the five catalogue selects are touched.

  const [response] = await Promise.all([
    page.waitForResponse(
      (res) =>
        res.url().includes("/api/v1/filament") &&
        res.request().method() === "POST",
    ),
    dialog.getByRole("button", { name: "Add 1 spool", exact: true }).click(),
  ]);
  await expect(dialog).toBeHidden();

  const created = (await response.json()) as { id: number };
  const filament = await apiFilament(page, created.id);
  expect(filament.spool_type ?? null).toBeNull();
  expect(filament.finish ?? null).toBeNull();
  expect(filament.pattern ?? null).toBeNull();
  expect(filament.translucent ?? null).toBeNull();
  expect(filament.glow ?? null).toBeNull();
});
