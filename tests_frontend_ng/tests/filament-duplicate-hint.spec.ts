import { expect, test, type Locator, type Page } from "@playwright/test";
import { post, seedFilament, unique } from "./helpers";

/**
 * `FilamentDuplicateHint` (client_v2/src/lib/ng/components/FilamentDuplicateHint.svelte),
 * mounted on the new-filament form (NewFilamentCards.svelte) alongside the name/material/colour
 * fields.
 *
 * Only the exact-match tier is exercised here, the same reasoning as duplicate-hint.spec.ts: it
 * needs no AI configuration, unlike the decision-model suggestion. A punctuation- and
 * case-different spelling of an existing filament's name ("galaxy-black" against a seeded
 * "Galaxy Black") is exactly the case the exact tier exists for.
 *
 * The "Use" button switches the add-spool flow onto the match the same way picking it from the
 * search results would (AddSpoolModal's `useExistingFilament` -> `choose()`), so the first test
 * below also exercises that switch end to end: after the click the chosen-filament row replaces
 * the new-filament cards, and saving creates the spool on that filament's id, not a fresh one.
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

/** Seed a vendor and a filament, with the exact fields the exact-match tier compares. */
async function seedGalaxyBlack(request: import("@playwright/test").APIRequestContext) {
  const vendorName = unique("GalaxyVendor");
  const vendor = await post(request, "/vendor", { name: vendorName });
  const name = unique("Galaxy Black");
  const filament = await post(request, "/filament", {
    name,
    vendor_id: vendor.id,
    material: "PLA",
    color_hex: "000000",
    density: 1.24,
    diameter: 1.75,
    weight: 1000,
    spool_weight: 190,
  });
  return { vendorName, name, filamentId: filament.id };
}

/**
 * Types the seeded vendor and a punctuation/case-different spelling of the seeded name into the
 * new-filament form, with material and colour matching exactly -- everything the exact tier
 * needs bar the colour, which callers set separately.
 */
async function fillMatchingDraft(
  dialog: Locator,
  vendorName: string,
  name: string,
): Promise<void> {
  await dialog.getByPlaceholder("e.g. Polymaker").fill(vendorName);
  await dialog
    .getByPlaceholder("e.g. PolyTerra Matte Sage")
    .fill(name.toLowerCase().replace(/ /g, "-"));
  await dialog.getByPlaceholder("PLA").fill("PLA");
}

test("an exact spelling/case/punctuation match offers the existing filament, and using it switches the flow onto it", async ({
  page,
  request,
}) => {
  const { vendorName, name, filamentId } = await seedGalaxyBlack(request);

  await page.goto("/", { waitUntil: "networkidle" });
  const dialog = await openAddSpoolModal(page);
  await dialog.getByRole("button", { name: /^Create a new filament/ }).click();

  await fillMatchingDraft(dialog, vendorName, name);
  await dialog.getByPlaceholder("hex").fill("000000");

  const label = `${vendorName} ${name} (PLA)`;
  await expect(dialog.getByText(`This filament already exists: ${label}.`)).toBeVisible();

  const useButton = dialog.getByRole("button", { name: `Use ${label}` });
  await expect(useButton).toBeVisible();
  await useButton.click();

  // Switched onto the existing filament: the new-filament cards (and their hint) are gone,
  // replaced by the chosen-filament row that picking it from search would have shown.
  await expect(dialog.getByPlaceholder("e.g. PolyTerra Matte Sage")).toHaveCount(0);
  const chosenRow = dialog.locator(".chosen");
  await expect(chosenRow).toContainText(name);
  await expect(chosenRow).toContainText(vendorName);

  await dialog.getByRole("button", { name: /^Add \d+ spool/ }).click();
  await expect(dialog).toBeHidden();

  // The spool was created against the existing filament's id, not a freshly minted duplicate.
  const spools = (await (
    await request.get(`/api/v1/spool?filament.id=${filamentId}`)
  ).json()) as { filament: { id: number } }[];
  expect(spools.length).toBeGreaterThan(0);
  expect(spools.every((s) => s.filament.id === filamentId)).toBe(true);
});

test("ChangeFilamentModal: using a hint switches the slot onto the existing filament", async ({
  page,
  request,
}) => {
  // The spool being changed, so its own filament is what excludeId keeps out of the check --
  // otherwise typing its own name/material/colour back would just offer itself.
  const current = await seedFilament(request, "CFCurrent");
  const spool = await post(request, "/spool", { filament_id: current.id });
  const { vendorName, name, filamentId } = await seedGalaxyBlack(request);

  await page.goto(`/?sel=spool:${spool.id}`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Change", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /^Create a new filament/ }).click();

  await fillMatchingDraft(dialog, vendorName, name);
  await dialog.getByPlaceholder("hex").fill("000000");

  const label = `${vendorName} ${name} (PLA)`;
  const useButton = dialog.getByRole("button", { name: `Use ${label}` });
  await expect(useButton).toBeVisible();
  await useButton.click();

  // The "Change to" side now shows the existing filament, the same as picking it from the
  // search results would.
  const nextSide = dialog.locator(".side").nth(1);
  await expect(nextSide).toContainText(name);
  await expect(nextSide).toContainText(vendorName);

  await dialog.getByRole("button", { name: "Change filament", exact: true }).click();
  await expect(dialog).toBeHidden();

  const res = await request.get(`/api/v1/spool/${spool.id}`);
  const body = (await res.json()) as { filament: { id: number } };
  expect(body.filament.id).toBe(filamentId);
});

test("changing the colour hides the hint immediately, not once a new answer arrives", async ({
  page,
  request,
}) => {
  const { vendorName, name } = await seedGalaxyBlack(request);

  await page.goto("/", { waitUntil: "networkidle" });
  const dialog = await openAddSpoolModal(page);
  await dialog.getByRole("button", { name: /^Create a new filament/ }).click();

  await fillMatchingDraft(dialog, vendorName, name);
  const colorInput = dialog.getByPlaceholder("hex");
  await colorInput.fill("000000");

  const hint = dialog.getByText(`This filament already exists: ${vendorName} ${name} (PLA).`);
  await expect(hint).toBeVisible();

  // A different colour is a different product, so the match found for black must not linger
  // once the field has moved on to red -- a tight timeout, well under the 500 ms debounce,
  // rather than staying visible until a fresh (negative) answer happens to arrive.
  await colorInput.fill("ff0000");
  await expect(hint).toBeHidden({ timeout: 100 });
});

test("a name too short to check yet fires no similar-filament request, even with a material picked", async ({
  page,
  request,
}) => {
  // Not uniquified, the same reasoning as duplicate-hint.spec.ts's own one-letter case: "too
  // short" has to mean a one-letter name, which unique() cannot produce.
  await seedGalaxyBlack(request);

  await page.goto("/", { waitUntil: "networkidle" });
  const dialog = await openAddSpoolModal(page);
  await dialog.getByRole("button", { name: /^Create a new filament/ }).click();

  const sawRequest = page
    .waitForRequest((r) => r.url().includes("/filament/similar"), { timeout: 1000 })
    .then(() => true)
    .catch(() => false);
  // The server's exact tier needs a name -- a material alone never matches -- so picking a
  // material first, with the name still too short to check, must not fire a request either.
  await dialog.getByPlaceholder("PLA").fill("PLA");
  await dialog.getByPlaceholder("e.g. PolyTerra Matte Sage").fill("G");

  expect(await sawRequest).toBe(false);
});
