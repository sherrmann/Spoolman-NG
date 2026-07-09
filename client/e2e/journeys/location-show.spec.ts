import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";
import { atPath } from "../helpers";

// The location show page (#90) is where a scanned location QR (the L-<id> scheme) resolves. It must
// render the location and the spools currently stored there. Camera scanning itself isn't
// exercisable in Playwright — the scan.ts round-trip is unit-tested — so this drives the resolved
// target directly.

test.describe("location show journey", () => {
  test("shows the location and the spools stored at it (#90)", async ({ page, request }) => {
    const stamp = Date.now();
    const locName = `E2E Show ${stamp}`;

    // Create the location entity and a spool stored at that location name.
    const loc = await (await request.post(`${APP_BASE_URL}/api/v1/locations`, { data: { name: locName } })).json();
    const fil = await (
      await request.post(`${APP_BASE_URL}/api/v1/filament`, {
        data: { name: `LS ${stamp}`, density: 1.24, diameter: 1.75, weight: 1000 },
      })
    ).json();
    const spool = await (
      await request.post(`${APP_BASE_URL}/api/v1/spool`, { data: { filament_id: fil.id, location: locName } })
    ).json();

    // Navigate straight to the show target (what the L-<id> scan resolves to).
    await page.goto(`${APP_BASE_URL}/location/show/${loc.id}`);
    await expect(page).toHaveURL(atPath(`/location/show/${loc.id}`));

    // The location name renders, and the "Spools at this location" table links the stored spool.
    await expect(page.getByText(locName, { exact: false }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Spools at this location" })).toBeVisible();
    await expect(page.getByRole("link", { name: `#${spool.id}` })).toBeVisible();
  });
});
