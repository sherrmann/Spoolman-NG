import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Location custom fields (#103): a field defined for the "location" entity shows in its settings
// tab, and its value can be set per-location from the board's gear (which lazily creates the
// Location entity row for that board column and persists the value).

test.describe("location custom fields journey", () => {
  test("define a location field, then set its value from the board", async ({ page, request }) => {
    const stamp = Date.now();
    const key = `humidity_${stamp}`;
    const fieldName = `Humidity ${stamp}`;
    const locName = `E2E Box ${stamp}`;

    // Define a text field on the location entity via the API.
    const fieldRes = await request.post(`${APP_BASE_URL}/api/v1/field/location/${key}`, {
      data: { name: fieldName, field_type: "text" },
    });
    expect(fieldRes.ok()).toBeTruthy();

    // Seed a spool at a location so the board renders a column for it.
    const fil = await (
      await request.post(`${APP_BASE_URL}/api/v1/filament`, {
        data: { name: `LF ${stamp}`, density: 1.24, diameter: 1.75, weight: 1000 },
      })
    ).json();
    await request.post(`${APP_BASE_URL}/api/v1/spool`, { data: { filament_id: fil.id, location: locName } });

    // The field appears in the new "Location" custom-fields settings tab.
    await page.goto(`${APP_BASE_URL}/settings/extra/location`);
    await expect(page.getByText(fieldName).first()).toBeVisible();

    // On the board, the location column now offers a custom-fields gear (only because a field exists).
    await page.goto(`${APP_BASE_URL}/locations`);
    const container = page.locator(".loc-container").filter({ hasText: locName });
    await expect(container).toBeVisible();
    await container.locator('button[title="Custom fields"]').click();

    // Fill the field in the modal and save.
    const input = page.getByLabel(fieldName);
    await input.fill("32%");
    await page.getByRole("button", { name: "OK" }).click();

    // The value persisted on the lazily-created Location entity (stored JSON-encoded).
    await expect
      .poll(async () => {
        const list = await (
          await request.get(`${APP_BASE_URL}/api/v1/locations?name=${encodeURIComponent(locName)}`)
        ).json();
        const match = list.find((l: { name: string; extra: Record<string, string> }) => l.name === locName);
        return match?.extra?.[key];
      })
      .toBe('"32%"');

    // Reopening the gear shows the saved value.
    await container.locator('button[title="Custom fields"]').click();
    await expect(page.getByLabel(fieldName)).toHaveValue("32%");
  });
});
