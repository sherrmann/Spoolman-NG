import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Spool-list sort + filter journey (TESTING_STRATEGY "Remaining"). The journey
// suite shares one backend DB, so every assertion is scoped to spools seeded with
// a unique material; sorting asserts relative order of the seeded ids only.

test.describe("spool list sort and filter", () => {
  test("filter by material, then sort by id in both directions", async ({ page, request }) => {
    const material = `E2EMAT${Date.now()}`;
    const fil = await (
      await request.post(`${APP_BASE_URL}/api/v1/filament`, {
        data: { name: `List ${Date.now()}`, material, density: 1.24, diameter: 1.75, weight: 1000 },
      })
    ).json();
    const ids: number[] = [];
    for (let i = 0; i < 3; i++) {
      const spool = await (
        await request.post(`${APP_BASE_URL}/api/v1/spool`, { data: { filament_id: fil.id } })
      ).json();
      ids.push(spool.id as number);
    }

    await page.goto(`${APP_BASE_URL}/spool`);
    await expect(page.getByRole("heading", { name: "Spools" })).toBeVisible();
    await page.getByRole("button", { name: "Clear Filters" }).click();

    // Applying the material filter through antd's dropdown is timing-sensitive: its option list
    // refetches as the dropdown opens (Material is an enumerated checkbox filter), and a checkbox or
    // OK click landing during that re-render can be dropped — leaving an EMPTY filter. That surfaced
    // as two different CI flakes: a lingering pre-filter row, or an OK that never fires the filtered
    // request (waitForResponse then hangs). Retry the whole open→check→OK until the server actually
    // returns the filtered list — its URL carries the unique per-run material value, so a match here
    // proves the filter was applied, not merely that some spool GET happened.
    await expect(async () => {
      await page.locator("th", { hasText: "Material" }).locator(".ant-table-filter-trigger").first().click();
      // antd renders a hidden measure row that duplicates header cells, so take the first visible one.
      const dropdown = page.locator(".ant-table-filter-dropdown:visible");
      const option = dropdown.locator(".ant-dropdown-menu-item").filter({ hasText: material });
      await expect(option).toBeVisible({ timeout: 5000 });
      if ((await option.locator(".ant-checkbox-checked").count()) === 0) {
        await option.click();
      }
      await expect(option.locator(".ant-checkbox-checked")).toBeVisible({ timeout: 2000 });
      await Promise.all([
        page.waitForResponse(
          (r) => r.url().includes("/api/v1/spool") && r.url().includes(material) && r.request().method() === "GET",
          { timeout: 8000 },
        ),
        dropdown.getByRole("button", { name: "OK" }).click(),
      ]);
    }).toPass({ timeout: 30000 });

    // Only the three seeded spools remain, in ascending id order (Clear Filters restored id asc).
    // The ID column is the second cell — the first is the row-selection checkbox column. Poll on the
    // exact seeded id set rather than a bare row count: a slow/duplicate filter refetch could leave a
    // stale row visible for a moment, which a snapshot count raced (observed as a CI flake). Polling
    // waits for the filtered list to settle to exactly these ids.
    const firstCol = page.locator(".ant-table-tbody tr.ant-table-row td:nth-child(2)");
    const rowIds = async () => (await firstCol.allInnerTexts()).map((t) => Number(t));
    await expect.poll(rowIds, { timeout: 15000 }).toEqual([...ids].sort((a, b) => a - b));

    // Sort by ID descending (default restored by Clear Filters is id asc).
    await page.locator("th", { hasText: /^ID/ }).locator(".ant-table-column-sorters").first().click();
    await expect.poll(rowIds, { timeout: 15000 }).toEqual([...ids].sort((a, b) => b - a));
  });
});
