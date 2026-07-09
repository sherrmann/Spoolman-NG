import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";
import { saveAndGetId } from "../helpers";

// Printer entity journey (#75): printers are managed from Settings (not a nav resource), and a spool
// is assigned to one from the spool form once at least one printer exists.

test.describe("printer journey", () => {
  test("create a printer in Settings, then assign a spool to it (#75)", async ({ page, request }) => {
    const printerName = `Voron ${Date.now()}`;

    // Settings → Printers: add a printer via the round + button and its modal.
    await page.goto(`${APP_BASE_URL}/settings/printers`);
    await expect(page.getByText("Manage your printers here", { exact: false })).toBeVisible();
    await page.locator(".ant-btn-circle").click();
    await page.getByLabel("Name").fill(printerName);
    await page.getByRole("button", { name: "OK" }).click();

    // It appears in the table and exists via the API.
    await expect(page.getByRole("cell", { name: printerName })).toBeVisible();
    const printers = await (await request.get(`${APP_BASE_URL}/api/v1/printer`)).json();
    const printer = printers.find((p: { name: string }) => p.name === printerName);
    expect(printer).toBeTruthy();

    // Assign a spool to it from the spool create form (the Printer select shows now that one exists).
    const fil = await (
      await request.post(`${APP_BASE_URL}/api/v1/filament`, {
        data: { name: `PF ${Date.now()}`, density: 1.24, diameter: 1.75, weight: 1000 },
      })
    ).json();
    await page.goto(`${APP_BASE_URL}/spool/create`);
    const filamentSelect = page.getByLabel("Filament");
    await filamentSelect.click();
    await filamentSelect.pressSequentially(fil.name);
    await page.locator(".ant-select-item-option").filter({ hasText: fil.name }).first().click();

    await page.getByLabel("Printer").click();
    await page.locator(".ant-select-item-option").filter({ hasText: printerName }).click();

    const id = await saveAndGetId(page, "spool");
    const spool = await (await request.get(`${APP_BASE_URL}/api/v1/spool/${id}`)).json();
    expect(spool.printer.id).toBe(printer.id);

    // The show page renders the assigned printer.
    await page.goto(`${APP_BASE_URL}/spool/show/${id}`);
    await expect(page.getByText(printerName).first()).toBeVisible();
  });

  test("the printer select is hidden when no printers exist (#75)", async ({ page, request }) => {
    // Seed only a filament; with no printers, the spool form must not show a Printer field.
    const fil = await (
      await request.post(`${APP_BASE_URL}/api/v1/filament`, {
        data: { name: `NP ${Date.now()}`, density: 1.24, diameter: 1.75, weight: 1000 },
      })
    ).json();
    // Ensure a clean slate: remove any printers left by other tests.
    const existing = await (await request.get(`${APP_BASE_URL}/api/v1/printer`)).json();
    for (const p of existing) {
      await request.delete(`${APP_BASE_URL}/api/v1/printer/${p.id}`);
    }

    await page.goto(`${APP_BASE_URL}/spool/create`);
    const filamentSelect = page.getByLabel("Filament");
    await filamentSelect.click();
    await filamentSelect.pressSequentially(fil.name);
    await page.locator(".ant-select-item-option").filter({ hasText: fil.name }).first().click();
    // No printers → no Printer field on the form.
    await expect(page.getByLabel("Printer")).toHaveCount(0);
  });
});
