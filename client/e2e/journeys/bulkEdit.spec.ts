import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Bulk-edit journey (#73). Seeds a filament and two spools through the API, then drives the real
// spool list: filter to the two spools, select them, and bulk-set their location. Verifies the
// change actually reached the backend (the bulk action loops the existing single-spool PATCH), so
// this exercises the compat-safe "no bulk endpoint" path end to end.

test.describe("spool bulk edit", () => {
  test("select two spools and bulk-set their location", async ({ page, request }) => {
    const marker = `BULK${Date.now()}`;
    const newLocation = `Shelf ${marker}`;

    const filRes = await request.post(`${APP_BASE_URL}/api/v1/filament`, {
      data: { name: marker, density: 1.24, diameter: 1.75, weight: 1000 },
    });
    expect(filRes.ok()).toBeTruthy();
    const filamentId = (await filRes.json()).id;

    const spoolIds: number[] = [];
    for (let i = 0; i < 2; i++) {
      const res = await request.post(`${APP_BASE_URL}/api/v1/spool`, {
        data: { filament_id: filamentId, initial_weight: 1000, lot_nr: marker },
      });
      expect(res.ok()).toBeTruthy();
      spoolIds.push((await res.json()).id);
    }

    await page.goto(`${APP_BASE_URL}/spool`);
    await expect(page.getByRole("heading", { name: "Spools" })).toBeVisible();

    // Filter to just our two spools via the free-text search (matches lot_nr), so "select all"
    // selects exactly them regardless of what else is in the list.
    const search = page.getByPlaceholder(/search/i);
    await search.fill(marker);
    await search.press("Enter");
    await expect(page.locator("tbody tr.ant-table-row")).toHaveCount(2);

    // Select all (the header checkbox) → the contextual bulk bar appears.
    await page.locator(".ant-table-thead .ant-checkbox-input").click();
    const bulkBar = page.locator(".spool-bulk-actions");
    await expect(bulkBar.getByText("2 selected")).toBeVisible();

    // Open the bulk-edit modal, enable the Location field, set a new location, apply.
    // Scope to the bulk bar so we don't match the per-row "Edit" action buttons.
    await bulkBar.getByRole("button", { name: "Edit" }).click();
    const modal = page.locator(".ant-modal-content");
    await expect(modal.getByText(/Edit 2 spools/)).toBeVisible();
    // The first checkbox gates the Location row; ticking it enables the location AutoComplete
    // (the only combobox in the modal), which we then type the new location into.
    await modal.locator(".ant-checkbox-input").first().check();
    await modal.getByRole("combobox").fill(newLocation);

    let patches = 0;
    page.on("response", (r) => {
      if (/\/api\/v1\/spool\/\d+$/.test(r.url()) && r.request().method() === "PATCH") patches += 1;
    });
    await modal.getByRole("button", { name: "Apply" }).click();

    // One PATCH per selected spool.
    await expect.poll(() => patches, { timeout: 10_000 }).toBeGreaterThanOrEqual(2);

    // The change reached the backend for both spools.
    for (const id of spoolIds) {
      const got = await request.get(`${APP_BASE_URL}/api/v1/spool/${id}`);
      expect((await got.json()).location).toBe(newLocation);
    }
  });
});
