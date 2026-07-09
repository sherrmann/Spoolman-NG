import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// A custom (extra) field seeded via the API must surface both in the settings
// manager table and as a real control on the spool create form.

test.describe("extra fields journey", () => {
  test("seeded field shows in settings and on the create form", async ({ page, request }) => {
    const stamp = Date.now();
    const key = `e2e_note_${stamp}`;
    const name = `E2E Note ${stamp}`;
    const res = await request.post(`${APP_BASE_URL}/api/v1/field/spool/${key}`, {
      data: { name, field_type: "text" },
    });
    expect(res.ok()).toBeTruthy();

    // Settings extra-fields manager lists the field.
    await page.goto(`${APP_BASE_URL}/settings/extra/spool`);
    await expect(page.getByText(name).first()).toBeVisible();

    // The spool create form renders the field as a labelled control.
    await page.goto(`${APP_BASE_URL}/spool/create`);
    await expect(page.getByLabel(name)).toBeVisible();
  });

  test("a link field renders its value as a clickable templated link (#129)", async ({ page, request }) => {
    const stamp = Date.now();
    const key = `e2e_link_field_${stamp}`;
    const name = `E2E Link Field ${stamp}`;
    // A link field: the definition holds the base-URL template, each item stores only the short value.
    const field = await request.post(`${APP_BASE_URL}/api/v1/field/filament/${key}`, {
      data: { name, field_type: "link", link_template: "https://www.example.com/dp/{}" },
    });
    expect(field.ok()).toBeTruthy();
    const fil = await (
      await request.post(`${APP_BASE_URL}/api/v1/filament`, {
        data: { name: `LF ${stamp}`, density: 1.24, diameter: 1.75, extra: { [key]: JSON.stringify("B0ABCDEF") } },
      })
    ).json();

    await page.goto(`${APP_BASE_URL}/filament/show/${fil.id}`);
    const link = page.getByRole("link", { name: "B0ABCDEF" });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "https://www.example.com/dp/B0ABCDEF");
  });

  test('"Copy from Filament" is a spool-only field option (#118)', async ({ page }) => {
    // The linking option only makes sense for spools, so the column header is present there and
    // absent for filament fields. Target the column header specifically (the shared description
    // paragraph also mentions the phrase).
    await page.goto(`${APP_BASE_URL}/settings/extra/spool`);
    await expect(page.getByRole("columnheader", { name: "Copy from Filament" })).toBeVisible();
    await page.goto(`${APP_BASE_URL}/settings/extra/filament`);
    await expect(page.getByRole("columnheader", { name: "Copy from Filament" })).toHaveCount(0);
  });

  test("a new spool inherits a linked filament field at creation (#118)", async ({ page, request }) => {
    const stamp = Date.now();
    const key = `e2e_link_${stamp}`;
    const name = `E2E Link ${stamp}`;
    // Same-key field on both entities; the spool field is marked copy-from-filament.
    await request.post(`${APP_BASE_URL}/api/v1/field/filament/${key}`, { data: { name, field_type: "text" } });
    const linked = await request.post(`${APP_BASE_URL}/api/v1/field/spool/${key}`, {
      data: { name, field_type: "text", copy_from_filament: true },
    });
    expect(linked.ok()).toBeTruthy();

    // The setting surfaces in the UI as a spool-only column.
    await page.goto(`${APP_BASE_URL}/settings/extra/spool`);
    await expect(page.getByText(name).first()).toBeVisible();

    // A filament carries the source value; a spool that doesn't set it inherits it at creation.
    const fil = await (
      await request.post(`${APP_BASE_URL}/api/v1/filament`, {
        data: { density: 1.24, diameter: 1.75, extra: { [key]: JSON.stringify("A-123") } },
      })
    ).json();
    const spool = await (await request.post(`${APP_BASE_URL}/api/v1/spool`, { data: { filament_id: fil.id } })).json();
    expect(JSON.parse(spool.extra[key])).toBe("A-123");
  });
});
