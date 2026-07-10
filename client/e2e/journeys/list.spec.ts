import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Exercises the spool list's header controls (the biggest list component): archived
// toggle, clear filters, and the columns dropdown.

test.describe("spool list interactions", () => {
  test("archived toggle, clear filters, columns dropdown", async ({ page, request }) => {
    // Seed one spool so the list (and its selection/totals interplay) has a real row —
    // hermetic, so this spec doesn't depend on rows left behind by other specs.
    const marker = `ListSpec ${Date.now()}`;
    const filRes = await request.post(`${APP_BASE_URL}/api/v1/filament`, {
      data: { name: marker, density: 1.24, diameter: 1.75, weight: 1000 },
    });
    expect(filRes.ok()).toBeTruthy();
    const spoolRes = await request.post(`${APP_BASE_URL}/api/v1/spool`, {
      data: { filament_id: (await filRes.json()).id, initial_weight: 1000 },
    });
    expect(spoolRes.ok()).toBeTruthy();

    await page.goto(`${APP_BASE_URL}/spool`);
    await expect(page.getByRole("heading", { name: "Spools" })).toBeVisible();

    // Toggle to the archived-only view (empty here) and back to the active list.
    await page.getByRole("button", { name: /Archived/ }).click();
    await page.getByRole("button", { name: /Archived/ }).click();

    // Clear filters resets the table state.
    await page.getByRole("button", { name: "Clear Filters" }).click();

    // Column headers carry a drag-to-resize handle (#90).
    await expect(page.locator('th [aria-label="resize-column"]').first()).toBeVisible();

    // Narrow the list to the seeded spool so it is on the visible page regardless of what
    // other specs have created (the list sorts by id ascending, so a fresh row lands last).
    const search = page.getByPlaceholder(/search/i);
    await search.fill(marker);
    await search.press("Enter");
    await expect(page.locator("tbody tr.ant-table-row")).toHaveCount(1);

    // Totals row is always visible and summarises the shown spools (#134). Selecting a row
    // switches it to summarising the selection instead. The row checkbox can sit under antd's
    // sticky-header overlay, so dispatch the click straight to the input (force) — the
    // behaviour under test is the totals switch, not pointer reachability.
    await expect(page.getByText(/spools? shown/)).toBeVisible();
    const markerRowCheckbox = page
      .locator("tbody tr.ant-table-row")
      .filter({ hasText: marker })
      .locator(".ant-checkbox-input");
    await markerRowCheckbox.check({ force: true });
    await expect(markerRowCheckbox).toBeChecked();
    await expect(page.getByText(/spools? selected/)).toBeVisible();
    await markerRowCheckbox.uncheck({ force: true });
    await expect(page.getByText(/spools? shown/)).toBeVisible();

    // The Columns manager popover opens and lists toggleable/reorderable columns (#94).
    await page.getByRole("button", { name: /Columns/ }).click();
    const columnsPopover = page.locator(".ant-popover").first();
    await expect(columnsPopover).toBeVisible();
    await expect(columnsPopover.getByText("Material", { exact: true })).toBeVisible();
    // Each column row carries a drag handle for reordering.
    await expect(columnsPopover.locator('[aria-label="drag-column"]').first()).toBeVisible();
  });
});
