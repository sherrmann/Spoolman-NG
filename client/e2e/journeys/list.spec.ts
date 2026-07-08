import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Exercises the spool list's header controls (the biggest list component): archived
// toggle, clear filters, and the columns dropdown.

test.describe("spool list interactions", () => {
  test("archived toggle, clear filters, columns dropdown", async ({ page }) => {
    await page.goto(`${APP_BASE_URL}/spool`);
    await expect(page.getByRole("heading", { name: "Spools" })).toBeVisible();

    // Toggle archived visibility on and back off.
    await page.getByRole("button", { name: /Archived/ }).click();
    await page.getByRole("button", { name: /Archived/ }).click();

    // Clear filters resets the table state.
    await page.getByRole("button", { name: "Clear Filters" }).click();

    // Column headers carry a drag-to-resize handle (#90).
    await expect(page.locator('th [aria-label="resize-column"]').first()).toBeVisible();

    // Totals row toggles on and shows a summary of the shown spools (#134).
    await page.getByRole("button", { name: /Show Totals/ }).click();
    await expect(page.getByText(/spools? shown/)).toBeVisible();
    await page.getByRole("button", { name: /Hide Totals/ }).click();
    await expect(page.getByText(/spools? shown/)).toHaveCount(0);

    // The Columns manager popover opens and lists toggleable/reorderable columns (#94).
    await page.getByRole("button", { name: /Columns/ }).click();
    const columnsPopover = page.locator(".ant-popover").first();
    await expect(columnsPopover).toBeVisible();
    await expect(columnsPopover.getByText("Material", { exact: true })).toBeVisible();
    // Each column row carries a drag handle for reordering.
    await expect(columnsPopover.locator('[aria-label="drag-column"]').first()).toBeVisible();
  });
});
