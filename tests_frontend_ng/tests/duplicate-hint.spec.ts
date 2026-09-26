import { expect, test, type Locator, type Page } from "@playwright/test";
import { post, seedFilament, unique } from "./helpers";

/**
 * `DuplicateHint` (client_v2/src/lib/ng/components/DuplicateHint.svelte), mounted on the new
 * filament form wherever a brand-new manufacturer name is typed.
 *
 * Only the exact-match tier is exercised here: it needs no AI configuration at all, unlike the
 * decision-model suggestion, which is off by default and requires an endpoint this suite has no
 * throwaway instance of. "e-Sun" against a seeded "eSUN" is exactly the case the exact tier
 * exists for -- same manufacturer once punctuation and case are ignored, but not equal by the
 * form's own case-insensitive vendor combobox, so the hint is the only thing that catches it.
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
 * ChangeVendorModal.svelte, opened from a filament's inspector. Unlike the new-filament form, a
 * manufacturer is already assigned here, which is what lets `excludeId` (and this suite's own
 * exclusion of the current vendor from any duplicate check) be exercised at all.
 *
 * Waits for the dialog's own GET /vendor -- the list it loads on open -- to come back, not just
 * for the dialog to be visible. A test that seeds a vendor right after this returns can then
 * rely on it being seeded strictly after that list was fetched, which is what "missing from the
 * loaded list" needs: a race here would make that test seed before the fetch and pass for the
 * wrong reason.
 */
async function openChangeVendorModal(
  page: Page,
  filamentId: number,
): Promise<Locator> {
  await page.goto(`/?sel=filament:${filamentId}`, { waitUntil: "networkidle" });
  const vendorsLoaded = page.waitForResponse(
    (r) => r.request().method() === "GET" && r.url().includes("/api/v1/vendor"),
  );
  await page.getByRole("button", { name: "Change", exact: true }).click();
  await vendorsLoaded;
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  return dialog;
}

test("typing a punctuation-different spelling of an existing manufacturer offers to use it", async ({
  page,
  request,
}) => {
  const vendorName = unique("eSUN");
  await post(request, "/vendor", { name: vendorName });

  await page.goto("/", { waitUntil: "networkidle" });
  const dialog = await openAddSpoolModal(page);
  await dialog.getByRole("button", { name: /^Create a new filament/ }).click();

  const manufacturer = dialog.getByPlaceholder("e.g. Polymaker");
  // Same letters and digits as the seeded vendor once case and punctuation are ignored, but not
  // equal to it as a plain case-insensitive string -- the client's own combobox match would miss
  // this, which is exactly why the hint's own exact-match request is what catches it.
  await manufacturer.fill(vendorName.replace("eSUN", "e-Sun"));

  const useButton = dialog.getByRole("button", { name: `Use ${vendorName}` });
  await expect(useButton).toBeVisible();
  await expect(
    dialog.getByText(`A manufacturer named ${vendorName} already exists.`),
  ).toBeVisible();

  await useButton.click();

  // Switched to the existing vendor: the field now holds its exact name, and the hint --
  // along with the "new manufacturer" extra fields it gated -- is gone, since the typed name
  // is no longer a new one.
  await expect(manufacturer).toHaveValue(vendorName);
  await expect(useButton).toBeHidden();
});

test("changing the name after a hint shows hides it immediately, not once a new answer arrives", async ({
  page,
  request,
}) => {
  const vendorName = unique("eSUN");
  await post(request, "/vendor", { name: vendorName });

  await page.goto("/", { waitUntil: "networkidle" });
  const dialog = await openAddSpoolModal(page);
  await dialog.getByRole("button", { name: /^Create a new filament/ }).click();

  const manufacturer = dialog.getByPlaceholder("e.g. Polymaker");
  await manufacturer.fill(vendorName.replace("eSUN", "e-Sun"));

  const useButton = dialog.getByRole("button", { name: `Use ${vendorName}` });
  await expect(useButton).toBeVisible();

  // Extend the name into something no longer close to the seeded vendor. The hint is keyed to
  // the name it was found for, so it must disappear right away -- a tight timeout, well under
  // the 500 ms debounce -- rather than staying visible and clickable until a fresh answer for
  // the new text happens to arrive.
  await manufacturer.fill(vendorName.replace("eSUN", "e-Sun") + " Pro");
  await expect(useButton).toBeHidden({ timeout: 100 });
});

test("a name too short to check yet fires no similar-vendor request", async ({
  page,
  request,
}) => {
  // Its exact key ("s") is exactly what typing "S" would key against -- so if the length floor
  // ever stopped gating the request, this is a match the exact tier would find and show. Not
  // uniquified: a one-letter name is what "too short" means, so unique() cannot be used here
  // without changing its key, and a stray leftover from an earlier run changes nothing this
  // test checks.
  await post(request, "/vendor", { name: "S." });

  await page.goto("/", { waitUntil: "networkidle" });
  const dialog = await openAddSpoolModal(page);
  await dialog.getByRole("button", { name: /^Create a new filament/ }).click();

  const manufacturer = dialog.getByPlaceholder("e.g. Polymaker");

  const sawRequest = page
    .waitForRequest((r) => r.url().includes("/vendor/similar"), {
      timeout: 1000,
    })
    .then(() => true)
    .catch(() => false);
  await manufacturer.fill("S");

  expect(await sawRequest).toBe(false);
  await expect(dialog.getByRole("button", { name: /^Use / })).toHaveCount(0);
});

test("Change manufacturer: using a hint already in the loaded vendor list selects it as existing", async ({
  page,
  request,
}) => {
  // Seeded before the dialog opens, so the vendor list ChangeVendorModal loads on open already
  // has it -- the ordinary case useExisting() resolves without a fetch.
  const vendorName = unique("eSUN");
  await post(request, "/vendor", { name: vendorName });
  // The filament's own manufacturer must differ from the seeded one, or excludeId would leave
  // it out of the duplicate check entirely and no hint would ever appear.
  const filament = await seedFilament(request, "CVExisting");

  const dialog = await openChangeVendorModal(page, filament.id);
  const search = dialog.getByPlaceholder("Search or name a manufacturer");
  await search.fill(vendorName.replace("eSUN", "e-Sun"));

  const useButton = dialog.getByRole("button", { name: `Use ${vendorName}` });
  await expect(useButton).toBeVisible();
  await useButton.click();

  // A real vendor, not the "create" row: the preview says nothing about creating it, and its own
  // card (name, empty-spool note) is what appears under "Change to".
  await expect(dialog.getByText("Will be created")).toHaveCount(0);
  const nextSide = dialog.locator(".side").nth(1);
  await expect(nextSide).toContainText(vendorName);
  await expect(nextSide).not.toContainText("Will be created");

  // The results list shows it selected among the vendors already there, not among the two rows
  // at the bottom (create/none).
  const vendorRow = dialog.locator(".res-item").filter({ hasText: vendorName });
  await expect(vendorRow).toHaveClass(/\bsel\b/);
});

test("Change manufacturer: using a hint missing from the loaded list still resolves and links it", async ({
  page,
  request,
}) => {
  const filament = await seedFilament(request, "CVMissing");

  const dialog = await openChangeVendorModal(page, filament.id);
  // openChangeVendorModal already waited for the dialog's own vendor-list fetch, so seeding here
  // guarantees this vendor is missing from `vendors` -- the case useExisting() has to fall back
  // from (fetching it by id) rather than mistakenly offering to create it again.
  const search = dialog.getByPlaceholder("Search or name a manufacturer");

  const vendorName = unique("eSUN");
  const vendor = await post(request, "/vendor", { name: vendorName });

  await search.fill(vendorName.replace("eSUN", "e-Sun"));
  const useButton = dialog.getByRole("button", { name: `Use ${vendorName}` });
  await expect(useButton).toBeVisible();
  await useButton.click();

  // Still a real vendor in the preview, not "will be created" -- the whole point of resolving it
  // by id when it isn't already in the loaded list.
  await expect(dialog.getByText("Will be created")).toHaveCount(0);
  await expect(dialog.locator(".side").nth(1)).toContainText(vendorName);

  await dialog
    .getByRole("button", { name: "Change manufacturer", exact: true })
    .click();
  await expect(dialog).toBeHidden();

  // Applying linked the filament to that vendor's own id, not a newly created duplicate of it.
  const res = await request.get(`/api/v1/filament/${filament.id}`);
  expect(res.ok()).toBeTruthy();
  const body = (await res.json()) as { vendor?: { id?: number } };
  expect(body.vendor?.id).toBe(vendor.id);
});
