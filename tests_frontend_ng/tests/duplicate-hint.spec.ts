import { expect, test, type Locator, type Page } from "@playwright/test";
import { post, unique } from "./helpers";

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
  await expect(dialog.getByText(`A manufacturer named ${vendorName} already exists.`)).toBeVisible();

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

test("a name too short to check yet fires no similar-vendor request", async ({ page, request }) => {
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
    .waitForRequest((r) => r.url().includes("/vendor/similar"), { timeout: 1000 })
    .then(() => true)
    .catch(() => false);
  await manufacturer.fill("S");

  expect(await sawRequest).toBe(false);
  await expect(dialog.getByRole("button", { name: /^Use / })).toHaveCount(0);
});
