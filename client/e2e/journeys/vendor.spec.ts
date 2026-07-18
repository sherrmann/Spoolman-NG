import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";
import { atPath, saveAndGetId, saveButton } from "../helpers";

// Whole-app journey against the REAL backend (API + temp SQLite). Vendors are
// labelled "Manufacturer" in the UI. The created id is read from the POST response
// so show/edit/clone navigate deterministically regardless of list sort/pagination.

test.describe("vendor (manufacturer) journey", () => {
  test("create → show → edit → clone", async ({ page }) => {
    const name = `Acme ${Date.now()}`;

    // List renders, then Create
    await page.goto(`${APP_BASE_URL}/vendor`);
    await expect(page.getByRole("heading", { name: "Manufacturers" })).toBeVisible();
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(atPath("/vendor/create"));

    // Fill and save; capture the new id from the create request. Role-based
    // locators here on purpose: right after the Create click the list is still
    // mounted while the create page's chunk loads, and getByLabel("Name") can
    // resolve to the list's sortable <th aria-label="Name"> (seen as a CI
    // flake). A th can never match textbox/spinbutton, and the locator waits
    // for the real form input.
    await page.getByRole("textbox", { name: "Name" }).fill(name);
    await page.getByRole("textbox", { name: "Comment" }).fill("made in e2e");
    await page.getByRole("spinbutton", { name: "Empty Spool Weight" }).fill("120");
    const id = await saveAndGetId(page, "vendor");
    await expect(page).toHaveURL(atPath("/vendor"));

    // Show page renders the created record
    await page.goto(`${APP_BASE_URL}/vendor/show/${id}`);
    await expect(page.getByText(name, { exact: false }).first()).toBeVisible();
    // exact: the timestamped vendor name above can itself contain "120" (e.g.
    // "Mainsail 1784354360120"), which trips strict mode on a substring match.
    await expect(page.getByText("120", { exact: true })).toBeVisible();

    // Edit (header button on the show page) → change the empty spool weight
    await page.getByRole("button", { name: "Edit" }).first().click();
    await expect(page).toHaveURL(atPath(`/vendor/edit/${id}`));
    await page.getByRole("spinbutton", { name: "Empty Spool Weight" }).fill("240");
    await saveButton(page).click();
    await expect(page).toHaveURL(atPath("/vendor"));

    // Clone into a new manufacturer
    const cloneName = `${name} Clone`;
    await page.goto(`${APP_BASE_URL}/vendor/clone/${id}`);
    await page.getByRole("textbox", { name: "Name" }).fill(cloneName);
    const cloneId = await saveAndGetId(page, "vendor");
    expect(cloneId).not.toBe(id);
    await expect(page).toHaveURL(atPath("/vendor"));
  });

  test("warns without blocking on a duplicate manufacturer name (#82)", async ({ page, request }) => {
    const name = `Dup ${Date.now()}`;
    // Seed an existing manufacturer via the API.
    const seed = await request.post(`${APP_BASE_URL}/api/v1/vendor`, { data: { name } });
    expect(seed.ok()).toBeTruthy();

    await page.goto(`${APP_BASE_URL}/vendor/create`);
    // Enter a case-variant of the existing name — the check is case/whitespace-insensitive.
    await page.getByRole("textbox", { name: "Name" }).fill(name.toUpperCase());

    // The soft warning appears once the existing manufacturers have loaded...
    await expect(page.getByText("A manufacturer with this name already exists.")).toBeVisible();

    // ...but it does NOT block: saving still creates the (duplicate) manufacturer and returns to the list.
    const id = await saveAndGetId(page, "vendor");
    expect(id).toBeGreaterThan(0);
    await expect(page).toHaveURL(atPath("/vendor"));
  });

  test("pressing Enter in a field submits the create form (#127)", async ({ page }) => {
    const name = `Enter ${Date.now()}`;
    await page.goto(`${APP_BASE_URL}/vendor/create`);
    const nameInput = page.getByRole("textbox", { name: "Name" });
    await nameInput.fill(name);
    await nameInput.press("Enter");
    // Enter saves and returns to the list (same as clicking Save).
    await expect(page).toHaveURL(atPath("/vendor"));
  });
});
