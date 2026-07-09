import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Filament bulk-edit journey (#73, upstream #749). Seeds two filaments through the API, then drives
// the real filament list: filter to them, select them, and bulk-set their price. Verifies the change
// reached the backend for both (the bulk action loops the existing single-filament PATCH).

test.describe("filament bulk edit", () => {
  test("select two filaments and bulk-set their price", async ({ page, request }) => {
    const marker = `FBULK${Date.now()}`;

    const ids: number[] = [];
    for (let i = 0; i < 2; i++) {
      const res = await request.post(`${APP_BASE_URL}/api/v1/filament`, {
        data: { name: `${marker}-${i}`, density: 1.24, diameter: 1.75, weight: 1000 },
      });
      expect(res.ok()).toBeTruthy();
      ids.push((await res.json()).id);
    }

    await page.goto(`${APP_BASE_URL}/filament`);
    await expect(page.getByRole("heading", { name: "Filaments" })).toBeVisible();

    // Filter to just our two filaments via the free-text search (matches name).
    const search = page.getByPlaceholder(/search/i);
    await search.fill(marker);
    await search.press("Enter");
    await expect(page.locator("tbody tr.ant-table-row")).toHaveCount(2);

    // Select all → the contextual bulk bar appears.
    await page.locator(".ant-table-thead .ant-checkbox-input").click();
    const bulkBar = page.locator(".filament-bulk-actions");
    await expect(bulkBar.getByText("2 selected")).toBeVisible();

    // Open the bulk-edit modal, enable Price (the first row), set a value, apply.
    await bulkBar.getByRole("button", { name: "Edit" }).click();
    const modal = page.locator(".ant-modal-content");
    await expect(modal.getByText(/Edit 2 filaments/)).toBeVisible();
    await modal.locator(".ant-checkbox-input").first().check();
    await modal.getByRole("spinbutton").first().fill("42.5");

    let patches = 0;
    page.on("response", (r) => {
      if (/\/api\/v1\/filament\/\d+$/.test(r.url()) && r.request().method() === "PATCH") patches += 1;
    });
    await modal.getByRole("button", { name: "Apply" }).click();

    await expect.poll(() => patches, { timeout: 10_000 }).toBeGreaterThanOrEqual(2);

    for (const id of ids) {
      const got = await request.get(`${APP_BASE_URL}/api/v1/filament/${id}`);
      expect((await got.json()).price).toBe(42.5);
    }
  });
});
