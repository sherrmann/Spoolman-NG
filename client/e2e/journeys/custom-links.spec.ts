import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Custom links journeys: user-configured sidebar links (#92) and per-spool action links (#140),
// both edited from Settings and stored in the generic settings store.

test.describe("custom links journey", () => {
  test("a custom sidebar link appears in the nav (#92)", async ({ page }) => {
    const name = `Mainsail ${Date.now()}`;
    await page.goto(`${APP_BASE_URL}/settings/custom-links`);
    await page.locator(".ant-btn-circle").click();
    await page.getByLabel("Name").fill(name);
    await page.getByLabel("URL", { exact: true }).fill("http://example.com/mainsail");
    await page.getByRole("button", { name: "OK" }).click();

    // The new link shows in the left sidebar as an external link (invalidated + refetched live).
    const link = page.getByRole("link", { name });
    await expect(link).toHaveAttribute("href", "http://example.com/mainsail");
    await expect(link).toHaveAttribute("target", "_blank");
  });

  test("a custom spool action link appears on the spool show page (#140)", async ({ page, request }) => {
    const actionName = `Set Active ${Date.now()}`;
    await page.goto(`${APP_BASE_URL}/settings/spool-links`);
    await page.locator(".ant-btn-circle").click();
    await page.getByLabel("Name").fill(actionName);
    await page.getByLabel("URL Template").fill("http://moonraker.local/set?id={id}");
    await page.getByRole("button", { name: "OK" }).click();

    // A spool to view.
    const fil = await (
      await request.post(`${APP_BASE_URL}/api/v1/filament`, {
        data: { name: `AL ${Date.now()}`, density: 1.24, diameter: 1.75, weight: 1000 },
      })
    ).json();
    const spool = await (await request.post(`${APP_BASE_URL}/api/v1/spool`, { data: { filament_id: fil.id } })).json();

    await page.goto(`${APP_BASE_URL}/spool/show/${spool.id}`);
    // The Actions dropdown appears (only because an action link is configured); it lists our link.
    await page.getByRole("button", { name: "Actions" }).click();
    await expect(page.getByRole("menuitem", { name: actionName })).toBeVisible();
  });
});
