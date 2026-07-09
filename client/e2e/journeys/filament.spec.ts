import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";
import { atPath, saveAndGetId, saveButton } from "../helpers";

// Filament CRUD journey through the UI. Only density + diameter are required.

test.describe("filament journey", () => {
  test("create → show → edit → clone", async ({ page }) => {
    const name = `PLA ${Date.now()}`;

    await page.goto(`${APP_BASE_URL}/filament`);
    await expect(page.getByRole("heading", { name: "Filaments" })).toBeVisible();
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(atPath("/filament/create"));

    // Role-based locators: after the Create click the list (with its sortable
    // <th aria-label="Name">) is still mounted while the create chunk loads, so
    // getByLabel can grab the header cell — same flake as vendor.spec.
    await page.getByRole("textbox", { name: "Name" }).fill(name);
    await page.getByRole("textbox", { name: "Material" }).fill("PLA");
    await page.getByRole("spinbutton", { name: "Density" }).fill("1.24");
    await page.getByRole("spinbutton", { name: "Diameter" }).fill("1.75");
    await page.getByRole("spinbutton", { name: "Weight" }).first().fill("1000");
    const id = await saveAndGetId(page, "filament");
    await expect(page).toHaveURL(atPath("/filament"));

    // Show
    await page.goto(`${APP_BASE_URL}/filament/show/${id}`);
    await expect(page.getByText(name, { exact: false }).first()).toBeVisible();

    // Edit → change material
    await page.getByRole("button", { name: "Edit" }).first().click();
    await expect(page).toHaveURL(atPath(`/filament/edit/${id}`));
    await page.getByRole("textbox", { name: "Material" }).fill("PETG");
    await saveButton(page).click();
    await expect(page).toHaveURL(atPath("/filament"));

    // Clone
    await page.goto(`${APP_BASE_URL}/filament/clone/${id}`);
    await page.getByRole("textbox", { name: "Name" }).fill(`${name} Clone`);
    const cloneId = await saveAndGetId(page, "filament");
    expect(cloneId).not.toBe(id);
  });

  test("density of 0 is rejected in the form (#67) and External ID round-trips (#70)", async ({ page, request }) => {
    const name = `EXT ${Date.now()}`;
    await page.goto(`${APP_BASE_URL}/filament/create`);
    await expect(page).toHaveURL(atPath("/filament/create"));

    await page.getByRole("textbox", { name: "Name" }).fill(name);
    // Density 0 must be caught client-side (backend requires > 0), not sent as a 422.
    await page.getByRole("spinbutton", { name: "Density" }).fill("0");
    await page.getByRole("spinbutton", { name: "Diameter" }).fill("1.75");
    await saveButton(page).click();
    await expect(page.getByText("Must be greater than 0.")).toBeVisible();
    await expect(page).toHaveURL(atPath("/filament/create"));

    // Fix the density and set an External ID (new on the create form).
    await page.getByRole("spinbutton", { name: "Density" }).fill("1.24");
    await page.getByRole("textbox", { name: "External ID" }).fill("ext-12875");
    const id = await saveAndGetId(page, "filament");

    const got = await request.get(`${APP_BASE_URL}/api/v1/filament/${id}`);
    expect((await got.json()).external_id).toBe("ext-12875");
  });

  test("create a new manufacturer inline from the vendor picker (#125)", async ({ page, request }) => {
    const vendorName = `Inline ${Date.now()}`;
    await page.goto(`${APP_BASE_URL}/filament/create`);
    await expect(page).toHaveURL(atPath("/filament/create"));

    await page.getByRole("textbox", { name: "Name" }).fill(`F ${Date.now()}`);
    await page.getByRole("spinbutton", { name: "Density" }).fill("1.24");
    await page.getByRole("spinbutton", { name: "Diameter" }).fill("1.75");

    // Open the Manufacturer picker and add a brand-new vendor via the dropdown's inline field.
    await page.getByLabel("Manufacturer").click();
    await page.getByPlaceholder("Add a new manufacturer").fill(vendorName);
    const [vendorRes] = await Promise.all([
      page.waitForResponse((r) => /\/api\/v1\/vendor$/.test(r.url()) && r.request().method() === "POST"),
      page.locator(".ant-select-dropdown").getByRole("button", { name: "Create" }).click(),
    ]);
    expect(vendorRes.ok()).toBeTruthy();
    const vendorId = (await vendorRes.json()).id;

    // The new vendor is auto-selected, so saving the filament references it — no page left.
    const id = await saveAndGetId(page, "filament");
    const got = await request.get(`${APP_BASE_URL}/api/v1/filament/${id}`);
    expect((await got.json()).vendor.id).toBe(vendorId);
  });

  test("extruder temperature range round-trips through the create form (#112)", async ({ page, request }) => {
    await page.goto(`${APP_BASE_URL}/filament/create`);
    await expect(page).toHaveURL(atPath("/filament/create"));

    await page.getByRole("textbox", { name: "Name" }).fill(`Range ${Date.now()}`);
    await page.getByRole("spinbutton", { name: "Density" }).fill("1.24");
    await page.getByRole("spinbutton", { name: "Diameter" }).fill("1.75");

    // The Min/Max pair share one labelled Form.Item; target it structurally (the two spinbuttons
    // inside it are min then max) rather than by an accessible name they don't individually carry.
    const range = page
      .locator(".ant-form-item")
      .filter({ has: page.locator(".ant-form-item-label", { hasText: "Extruder Temp Range" }) });
    await range.getByRole("spinbutton").first().fill("205");
    await range.getByRole("spinbutton").last().fill("225");

    const id = await saveAndGetId(page, "filament");
    const got = await (await request.get(`${APP_BASE_URL}/api/v1/filament/${id}`)).json();
    expect(got.settings_extruder_temp_min).toBe(205);
    expect(got.settings_extruder_temp_max).toBe(225);
  });
});
