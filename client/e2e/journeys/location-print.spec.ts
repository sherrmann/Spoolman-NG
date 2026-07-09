import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Location label printing (#84): the print page turns selected locations into scannable QR labels.

test.describe("location label printing journey", () => {
  test("renders a QR label for a location passed directly (from the show page)", async ({ page, request }) => {
    const stamp = Date.now();
    const locName = `E2E Print ${stamp}`;
    const loc = await (await request.post(`${APP_BASE_URL}/api/v1/locations`, { data: { name: locName } })).json();

    // This is the URL the location show page's "Print label" button navigates to.
    await page.goto(`${APP_BASE_URL}/location/print?locations=${loc.id}`);

    // The QR label and the location's name both render.
    await expect(page.locator(".ant-qrcode").first()).toBeVisible();
    await expect(page.getByText(locName).first()).toBeVisible();
  });

  test("selecting locations then continuing renders their labels", async ({ page, request }) => {
    const stamp = Date.now();
    const locName = `E2E Select ${stamp}`;
    await request.post(`${APP_BASE_URL}/api/v1/locations`, { data: { name: locName } });

    await page.goto(`${APP_BASE_URL}/location/print`);

    // Pick the location in the multi-select, close the dropdown, then continue to the labels.
    await page.locator(".ant-select-selector").click();
    await page.locator(".ant-select-item-option").filter({ hasText: locName }).first().click();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Continue" }).click();

    await expect(page.locator(".ant-qrcode").first()).toBeVisible();
  });
});
