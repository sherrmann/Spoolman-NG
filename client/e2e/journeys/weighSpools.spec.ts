import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Weigh-spools workflow (#99). Seeds a filament and spool, opens the header-level "Weigh Spools"
// dialog, searches for the spool, consumes some weight, and Save & Next. Verifies the change reached
// the backend (via the existing PUT /use) and that the dialog stays open for the next spool.

test.describe("weigh spools workflow", () => {
  test("search a spool, enter weight, Save & Next", async ({ page, request }) => {
    const marker = `WEIGH${Date.now()}`;
    const filRes = await request.post(`${APP_BASE_URL}/api/v1/filament`, {
      data: { name: marker, density: 1.24, diameter: 1.75, weight: 1000 },
    });
    expect(filRes.ok()).toBeTruthy();
    const filamentId = (await filRes.json()).id;
    const spoolRes = await request.post(`${APP_BASE_URL}/api/v1/spool`, {
      data: { filament_id: filamentId, initial_weight: 1000, used_weight: 0 },
    });
    const spoolId = (await spoolRes.json()).id;

    await page.goto(`${APP_BASE_URL}/spool`);
    await expect(page.getByRole("heading", { name: "Spools" })).toBeVisible();

    // Open the header workflow.
    await page.getByRole("button", { name: /Weigh Spools/ }).click();
    const modal = page.locator(".ant-modal-content");
    await expect(modal.getByText("Weigh Spools").first()).toBeVisible();

    // Search for the spool by its filament name and pick it.
    const spoolSelect = modal.getByRole("combobox");
    await spoolSelect.click();
    await spoolSelect.pressSequentially(marker);
    // antd portals the Select dropdown outside the modal, so match the option at page level.
    await page.locator(".ant-select-item-option").filter({ hasText: marker }).first().click();

    // Consume 150 g by weight.
    await modal.getByText("Weight", { exact: true }).click();
    await modal.getByLabel("Consume Amount").fill("150");
    const [useRes] = await Promise.all([
      page.waitForResponse((r) => /\/spool\/\d+\/use$/.test(r.url()) && r.request().method() === "PUT"),
      modal.getByRole("button", { name: "Save & Next" }).click(),
    ]);
    expect(useRes.ok()).toBeTruthy();

    // The dialog stays open for the next spool (save-and-update-more).
    await expect(modal.getByText("Weigh Spools").first()).toBeVisible();

    // The consumption reached the backend.
    const got = await request.get(`${APP_BASE_URL}/api/v1/spool/${spoolId}`);
    expect((await got.json()).used_weight).toBe(150);
  });
});
