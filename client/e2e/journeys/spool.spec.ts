import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";
import { atPath, saveAndGetId, saveButton } from "../helpers";

// Spool journey. A filament is seeded through the API so the UI test focuses on the
// spool create form (searchable filament Select + weight entry), show, edit, adjust
// and archive.

async function seedFilament(
  request: import("@playwright/test").APIRequestContext,
): Promise<{ id: number; name: string }> {
  const name = `Seed ${Date.now()}`;
  const res = await request.post(`${APP_BASE_URL}/api/v1/filament`, {
    data: { name, density: 1.24, diameter: 1.75, weight: 1000 },
  });
  expect(res.ok()).toBeTruthy();
  return { id: (await res.json()).id, name };
}

test.describe("spool journey", () => {
  test("create (select filament) → show → edit", async ({ page, request }) => {
    const filament = await seedFilament(request);

    await page.goto(`${APP_BASE_URL}/spool/create`);
    await expect(page).toHaveURL(atPath("/spool/create"));

    // Searchable filament Select: open, type the seeded name, pick the antd option.
    const filamentSelect = page.getByLabel("Filament");
    await filamentSelect.click();
    await filamentSelect.pressSequentially(filament.name);
    await page.locator(".ant-select-item-option").filter({ hasText: filament.name }).first().click();

    // used_weight defaults to 0 and initial_weight auto-fills from the filament, so a
    // comment is enough to make an identifiable, editable spool.
    await page.getByLabel("Comment").fill("e2e spool");

    const id = await saveAndGetId(page, "spool");
    await expect(page).toHaveURL(atPath("/spool"));

    // Show — the linked filament name is rendered
    await page.goto(`${APP_BASE_URL}/spool/show/${id}`);
    await expect(page.getByText(filament.name, { exact: false }).first()).toBeVisible();

    // Edit → change the comment
    await page.getByRole("button", { name: "Edit" }).first().click();
    await expect(page).toHaveURL(atPath(`/spool/edit/${id}`));
    await page.getByLabel("Comment").fill("e2e spool edited");
    await saveButton(page).click();
    await expect(page).toHaveURL(atPath("/spool"));
  });

  test("create multiple spools via the quantity stepper", async ({ page, request }) => {
    const filament = await seedFilament(request);

    await page.goto(`${APP_BASE_URL}/spool/create`);
    const filamentSelect = page.getByLabel("Filament");
    await filamentSelect.click();
    await filamentSelect.pressSequentially(filament.name);
    await page.locator(".ant-select-item-option").filter({ hasText: filament.name }).first().click();

    // Bump the quantity to 3 with the + stepper (the button right after the
    // quantity input's antd wrapper), then create the batch.
    const plus = page.locator(".ant-input-number:has(#qty-input) + button");
    await plus.click();
    await plus.click();
    await expect(page.locator("#qty-input")).toHaveValue("3");

    let posts = 0;
    page.on("response", (r) => {
      if (/\/api\/v1\/spool$/.test(r.url()) && r.request().method() === "POST") posts += 1;
    });
    await page
      .locator("button")
      .filter({ hasText: /^Save$/ })
      .click();
    await expect(page).toHaveURL(atPath("/spool"));
    // The batch fires one create per unit; they settle just after the redirect.
    await expect.poll(() => posts, { timeout: 10_000 }).toBeGreaterThanOrEqual(3);
  });

  test("measured weight survives an empty-weight correction (#66)", async ({ page, request }) => {
    // Filament with a known net + spool weight so Measured mode is enabled and gross is predictable.
    const name = `Meas ${Date.now()}`;
    const res = await request.post(`${APP_BASE_URL}/api/v1/filament`, {
      data: { name, density: 1.24, diameter: 1.75, weight: 1000, spool_weight: 200 },
    });
    expect(res.ok()).toBeTruthy();

    await page.goto(`${APP_BASE_URL}/spool/create`);
    const filamentSelect = page.getByLabel("Filament");
    await filamentSelect.click();
    await filamentSelect.pressSequentially(name);
    await page.locator(".ant-select-item-option").filter({ hasText: name }).first().click();

    // Enter a measured (gross) weight of 800 g. With gross 1200 (1000 + 200) that means used = 400.
    // The weight-mode radios/inputs have no form `name`, so target them structurally.
    await page.locator(".ant-radio-button-wrapper").filter({ hasText: "Measured Weight" }).click();
    const measured = page
      .locator(".ant-form-item")
      .filter({ has: page.locator(".ant-form-item-label", { hasText: "Measured Weight" }) })
      .getByRole("spinbutton");
    await measured.fill("800");

    // Now correct the empty-spool weight to 300. The scale still read 800, so the measured field must
    // STILL show 800 (previously it drifted to 900 because used_weight was held fixed) — #66.
    await page.getByRole("spinbutton", { name: "Empty Weight" }).fill("300");
    await expect(measured).toHaveValue(/800/);

    // used_weight is re-derived: gross 1300 − measured 800 = 500.
    const id = await saveAndGetId(page, "spool");
    const got = await request.get(`${APP_BASE_URL}/api/v1/spool/${id}`);
    expect((await got.json()).used_weight).toBe(500);
  });

  test("shows sibling spools of the same filament on the show page (#100)", async ({ page, request }) => {
    const filament = await seedFilament(request);
    // Two spools of the SAME filament.
    const a = await request.post(`${APP_BASE_URL}/api/v1/spool`, {
      data: { filament_id: filament.id, initial_weight: 1000 },
    });
    const b = await request.post(`${APP_BASE_URL}/api/v1/spool`, {
      data: { filament_id: filament.id, initial_weight: 1000, location: "Shelf Z" },
    });
    const aId = (await a.json()).id;
    const bId = (await b.json()).id;

    await page.goto(`${APP_BASE_URL}/spool/show/${aId}`);

    // The sibling section lists spool b (with its location) and links to it, but not spool a itself.
    await expect(page.getByRole("heading", { name: "Other spools of this filament" })).toBeVisible();
    await expect(page.getByRole("link", { name: `#${bId}` })).toBeVisible();
    await expect(page.getByText("Shelf Z")).toBeVisible();
    await expect(page.getByRole("link", { name: `#${aId}` })).toHaveCount(0);
  });

  test("per-spool diameter override round-trips through the create form (#101)", async ({ page, request }) => {
    const filament = await seedFilament(request);

    await page.goto(`${APP_BASE_URL}/spool/create`);
    const filamentSelect = page.getByLabel("Filament");
    await filamentSelect.click();
    await filamentSelect.pressSequentially(filament.name);
    await page.locator(".ant-select-item-option").filter({ hasText: filament.name }).first().click();

    // Enter a measured diameter that differs from the filament's nominal 1.75 mm.
    await page.getByRole("spinbutton", { name: "Diameter" }).fill("1.73");

    const id = await saveAndGetId(page, "spool");
    const got = await request.get(`${APP_BASE_URL}/api/v1/spool/${id}`);
    expect((await got.json()).diameter).toBe(1.73);
  });

  test("per-spool color override wins over the filament color in the swatch (#74)", async ({ page, request }) => {
    // Green filament, but this spool overrides to red.
    const name = `Color ${Date.now()}`;
    const fil = await (
      await request.post(`${APP_BASE_URL}/api/v1/filament`, {
        data: { name, density: 1.24, diameter: 1.75, weight: 1000, color_hex: "00FF00" },
      })
    ).json();
    const spool = await (
      await request.post(`${APP_BASE_URL}/api/v1/spool`, { data: { filament_id: fil.id, color_hex: "FF0000" } })
    ).json();

    await page.goto(`${APP_BASE_URL}/spool/show/${spool.id}`);
    // The swatch shows the spool's red override, not the filament's green.
    const segment = page.locator(".spool-icon > div").first();
    await expect(segment).toHaveCSS("background-color", "rgb(255, 0, 0)");
  });

  test("filament dropdown shows a colour swatch per option (#126)", async ({ page, request }) => {
    // Seed a coloured filament so its dropdown option renders a swatch.
    const name = `Swatch ${Date.now()}`;
    const res = await request.post(`${APP_BASE_URL}/api/v1/filament`, {
      data: { name, density: 1.24, diameter: 1.75, weight: 1000, color_hex: "FF0000" },
    });
    expect(res.ok()).toBeTruthy();

    await page.goto(`${APP_BASE_URL}/spool/create`);
    const filamentSelect = page.getByLabel("Filament");
    await filamentSelect.click();
    await filamentSelect.pressSequentially(name);
    // The matching option row renders a SpoolIcon swatch alongside the label (#126).
    const option = page.locator(".ant-select-item-option").filter({ hasText: name }).first();
    await expect(option.locator(".spool-icon")).toBeVisible();
  });

  test("adjust filament usage → archive", async ({ page, request }) => {
    const filament = await seedFilament(request);
    const spoolRes = await request.post(`${APP_BASE_URL}/api/v1/spool`, {
      data: { filament_id: filament.id, initial_weight: 1000, used_weight: 200 },
    });
    const spoolId = (await spoolRes.json()).id;

    await page.goto(`${APP_BASE_URL}/spool/show/${spoolId}`);

    // Adjust: open the modal, consume 100 g by weight, submit → PUT /use.
    await page.getByRole("button", { name: /Adjust Spool Filament/ }).click();
    const modal = page.locator(".ant-modal-content");
    await expect(modal.getByText("Adjust Spool Filament").first()).toBeVisible();
    await modal.getByText("Weight", { exact: true }).click();
    await modal.getByLabel("Consume Amount").fill("100");
    const [useRes] = await Promise.all([
      page.waitForResponse((r) => /\/spool\/\d+\/use$/.test(r.url()) && r.request().method() === "PUT"),
      page.getByRole("button", { name: "OK" }).click(),
    ]);
    expect(useRes.ok()).toBeTruthy();

    // Archive: header button → confirm dialog (remaining > 0) → PATCH archived=true.
    await page
      .locator("button")
      .filter({ hasText: /^Archive$/ })
      .click();
    const [archiveRes] = await Promise.all([
      page.waitForResponse((r) => /\/spool\/\d+$/.test(r.url()) && r.request().method() === "PATCH"),
      page.locator(".ant-modal-confirm .ant-btn-primary").click(),
    ]);
    expect(archiveRes.ok()).toBeTruthy();
    // The header now offers to unarchive.
    await expect(page.locator("button").filter({ hasText: /^Unarchive$/ })).toBeVisible();
  });
});
