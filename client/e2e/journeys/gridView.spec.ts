import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";
import { atPath } from "../helpers";

// Grid/gallery view (#139). Seeds a spool, switches the spool list into grid view, and confirms the
// spool renders as a clickable colour tile that opens its detail page.

test.describe("spool grid view", () => {
  test("toggle grid view and open a spool tile", async ({ page, request }) => {
    const marker = `GRID${Date.now()}`;
    const filRes = await request.post(`${APP_BASE_URL}/api/v1/filament`, {
      data: { name: marker, density: 1.24, diameter: 1.75, weight: 1000, color_hex: "00AAFF" },
    });
    expect(filRes.ok()).toBeTruthy();
    const filamentId = (await filRes.json()).id;
    const spoolRes = await request.post(`${APP_BASE_URL}/api/v1/spool`, {
      data: { filament_id: filamentId, initial_weight: 1000 },
    });
    const spoolId = (await spoolRes.json()).id;

    await page.goto(`${APP_BASE_URL}/spool`);
    await expect(page.getByRole("heading", { name: "Spools" })).toBeVisible();

    // Filter to just our spool so the grid holds exactly one tile.
    const search = page.getByPlaceholder(/search/i);
    await search.fill(marker);
    await search.press("Enter");
    await expect(page.locator("tbody tr.ant-table-row")).toHaveCount(1);

    // Switch to grid view — the table is replaced by colour-tile cards.
    await page.getByRole("button", { name: "Grid view" }).click();
    const card = page.locator(".ant-card").filter({ hasText: marker });
    await expect(card).toHaveCount(1);
    // The toggle now offers a way back to the table.
    await expect(page.getByRole("button", { name: "Table view" })).toBeVisible();

    // Clicking the tile opens the spool.
    await card.click();
    await expect(page).toHaveURL(atPath(`/spool/show/${spoolId}`));
  });
});
