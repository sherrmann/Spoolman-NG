import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Print-dialog permutations (TESTING_STRATEGY "Remaining"): the spool-select step
// (select-all, empty-selection error) and the QR dialog's template editing with its
// live label preview. The real Print button opens the browser print dialog, so it
// is asserted visible but never clicked.

async function seedSpool(request: import("@playwright/test").APIRequestContext, name: string): Promise<number> {
  const fil = await (
    await request.post(`${APP_BASE_URL}/api/v1/filament`, {
      data: { name, density: 1.24, diameter: 1.75, weight: 1000 },
    })
  ).json();
  const spool = await (await request.post(`${APP_BASE_URL}/api/v1/spool`, { data: { filament_id: fil.id } })).json();
  return spool.id as number;
}

test.describe("print dialog journeys", () => {
  test("spool selection step: empty-selection error, select all, continue to the dialog", async ({ page, request }) => {
    await seedSpool(request, `PrintSel ${Date.now()}`);

    // Without ?spools=… the printing page starts on the selection step.
    await page.goto(`${APP_BASE_URL}/spool/print`);
    await expect(page.getByText("Select spools to print labels for.")).toBeVisible();

    // Continuing with nothing selected is rejected with a message.
    await page.getByRole("button", { name: /Continue/ }).click();
    await expect(page.getByText("You have not selected any spools.")).toBeVisible();

    // Select/Unselect All checks every row and enables progress to the QR dialog.
    await page.getByText("Select/Unselect All").click();
    await expect(page.getByText(/spools? selected/)).toBeVisible();
    await page.getByRole("button", { name: /Continue/ }).click();
    await expect(page.getByRole("button", { name: /Print/ }).first()).toBeVisible();
  });

  test("label template edits update the rendered preview", async ({ page, request }) => {
    const spoolId = await seedSpool(request, `PrintTpl ${Date.now()}`);

    await page.goto(`${APP_BASE_URL}/spool/print?spools=${spoolId}`);
    await expect(page.getByRole("button", { name: /Print/ }).first()).toBeVisible();

    // The template editor lives in the collapsed "Content Settings" panel.
    await page.getByText("Content Settings", { exact: true }).click();

    // Replace the template with a marker that interpolates the spool id and
    // verify the live preview renders the interpolated text.
    const template = page.locator("textarea").first();
    await template.fill("E2E-MARKER {id}");
    await expect(page.getByText(`E2E-MARKER ${spoolId}`).first()).toBeVisible();

    // The template help "Show" button opens the tag-reference modal.
    await page.getByRole("button", { name: /^Show$/ }).click();
    await expect(page.locator(".ant-modal-content").last()).toBeVisible();
  });

  test("QR size setting shrinks the QR and warns when unscannably small (#295)", async ({ page, request }) => {
    const spoolId = await seedSpool(request, `QrSize ${Date.now()}`);

    await page.goto(`${APP_BASE_URL}/spool/print?spools=${spoolId}`);
    await expect(page.getByRole("button", { name: /Print/ }).first()).toBeVisible();
    await page.getByText("Content Settings", { exact: true }).click();

    // Auto (the default) fills half the label — the pre-#295 behavior.
    const qrContainer = page.locator(".print-qrcode-container").first();
    const autoWidth = (await qrContainer.boundingBox())?.width ?? 0;
    expect(autoWidth).toBeGreaterThan(0);

    // Switching to a custom size gives a definite mm basis well under the auto half-label.
    const qrSizeItem = page.locator(".ant-form-item", { hasText: "QR Size" }).first();
    await qrSizeItem.getByText("Custom", { exact: true }).click();
    await expect(async () => {
      const customWidth = (await qrContainer.boundingBox())?.width ?? 0;
      expect(customWidth).toBeGreaterThan(0);
      expect(customWidth).toBeLessThan(autoWidth);
    }).toPass();

    // Below the scannability floor a soft warning appears; back at a sane size it clears.
    await qrSizeItem.getByRole("spinbutton").fill("8");
    await expect(page.getByText(/can be hard to scan/)).toBeVisible();
    await qrSizeItem.getByRole("spinbutton").fill("20");
    await expect(page.getByText(/can be hard to scan/)).toHaveCount(0);

    // Auto restores the fill behavior.
    await qrSizeItem.getByText("Auto", { exact: true }).click();
    await expect(async () => {
      const restoredWidth = (await qrContainer.boundingBox())?.width ?? 0;
      expect(restoredWidth).toBeCloseTo(autoWidth, 0);
    }).toPass();
  });

  test("out-of-bounds label content raises the clipped-content warning", async ({ page, request }) => {
    // Deliberately short name: a long unbreakable token (like the timestamped names other
    // specs seed) genuinely clips in the default label's text box and would trip the
    // warning before we even change anything — the baseline below needs a label that fits.
    const spoolId = await seedSpool(request, `Clip${Date.now() % 100000}`);

    await page.goto(`${APP_BASE_URL}/spool/print?spools=${spoolId}`);
    await expect(page.getByRole("button", { name: /Print/ }).first()).toBeVisible();

    // A fitting label must not warn. Poll one measurement cycle in (the detector runs
    // rAF + delayed re-checks), so this doesn't pass merely by asserting too early.
    await page.waitForTimeout(1200);
    await expect(page.getByText("Some label content is cut off")).toHaveCount(0);

    // Stuff far more text into the label than a default-size cell can hold.
    await page.getByText("Content Settings", { exact: true }).click();
    const template = page.locator("textarea").first();
    await template.fill(Array(30).fill("CLIP-MARKER LINE {id}").join("\n"));

    // The live preview re-measures and surfaces the clipping warning.
    await expect(page.getByText("Some label content is cut off")).toBeVisible();

    // Restoring a fitting template clears the warning again.
    await template.fill("{id}");
    await expect(page.getByText("Some label content is cut off")).toHaveCount(0);
  });
});
