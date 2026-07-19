import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// Print-dialog permutations (TESTING_STRATEGY "Remaining"): the spool-select step
// (select-all, empty-selection error) and the QR dialog's template editing with its
// live label preview. Clicking Print opens the pre-print checklist (#296); tests
// interact with it via Cancel ONLY — "Print now" would invoke the real browser print
// pipeline, which hangs headless runs.

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

    // Top placement puts the mm basis on the height axis; the QR svg must stay inside
    // the reserved band instead of overflowing at its intrinsic 160px size (#295).
    await page.locator(".ant-form-item", { hasText: "QR Placement" }).first().getByText("Top", { exact: true }).click();
    await expect(async () => {
      const containerBox = await qrContainer.boundingBox();
      const svgBox = await page.locator(".print-qrcode-container svg").first().boundingBox();
      expect(containerBox).not.toBeNull();
      expect(svgBox).not.toBeNull();
      expect(svgBox!.height).toBeLessThanOrEqual(containerBox!.height + 1);
      expect(svgBox!.width).toBeLessThanOrEqual(containerBox!.width + 1);
    }).toPass();
    await page
      .locator(".ant-form-item", { hasText: "QR Placement" })
      .first()
      .getByText("Left", { exact: true })
      .click();

    // Auto restores the fill behavior.
    await qrSizeItem.getByText("Auto", { exact: true }).click();
    await expect(async () => {
      const restoredWidth = (await qrContainer.boundingBox())?.width ?? 0;
      expect(restoredWidth).toBeCloseTo(autoWidth, 0);
    }).toPass();
  });

  test("print button opens the pre-print checklist with the exact paper size (#296)", async ({ page, request }) => {
    const spoolId = await seedSpool(request, `Chk ${Date.now()}`);

    await page.goto(`${APP_BASE_URL}/spool/print?spools=${spoolId}`);
    await expect(page.getByRole("button", { name: /Print$/ })).toBeVisible();

    // Print does not fire immediately — the checklist warns about browser-dialog rescaling
    // first, quoting the exact page size the OS dialog must be set to (A4 default).
    await page.getByRole("button", { name: /Print$/ }).click();
    await expect(page.getByText("Before you print")).toBeVisible();
    await expect(page.getByText(/210 × 297/)).toBeVisible();

    // No label/auto mismatch on A4 ⇒ no page-size-mode hint.
    await expect(page.getByRole("button", { name: "Switch to Match label size" })).toHaveCount(0);

    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByText("Before you print")).toBeHidden();
  });

  test("checklist offers the page-size-mode switch for label paper on auto (#296)", async ({ page, request }) => {
    const spoolId = await seedSpool(request, `ChkLbl ${Date.now()}`);

    await page.goto(`${APP_BASE_URL}/spool/print?spools=${spoolId}`);
    await expect(page.getByRole("button", { name: /Print$/ })).toBeVisible();

    // Pick a curated label size while pageSizeMode stays "auto".
    await page.getByText("Layout Settings", { exact: true }).click();
    await page.locator(".ant-form-item", { hasText: "Paper Size" }).first().locator(".ant-select").click();
    await page.locator(".ant-select-item-option", { hasText: "Label 62×29 mm" }).click();

    await page.getByRole("button", { name: /Print$/ }).click();
    await expect(page.getByText("Before you print")).toBeVisible();
    await expect(page.getByText(/62 × 29/)).toBeVisible();

    // Applying the hint flips pageSizeMode to "label" and the hint disappears reactively.
    await page.getByRole("button", { name: "Switch to Match label size" }).click();
    await expect(page.getByRole("button", { name: "Switch to Match label size" })).toHaveCount(0);
    await page.getByRole("button", { name: "Cancel" }).click();
  });

  test("preview and settings sit side by side on wide screens and stack on narrow ones", async ({ page, request }) => {
    const spoolId = await seedSpool(request, `Layout ${Date.now()}`);

    await page.setViewportSize({ width: 1600, height: 900 });
    await page.goto(`${APP_BASE_URL}/spool/print?spools=${spoolId}`);
    const preview = page.locator(".print-page").first();
    const settings = page.getByText("Skip Items", { exact: true });
    await expect(preview).toBeVisible();

    // Side by side: the settings column overlaps the preview's vertical range.
    const wideP = (await preview.boundingBox())!;
    const wideS = (await settings.boundingBox())!;
    expect(wideS.y).toBeLessThan(wideP.y + wideP.height);
    expect(wideS.x).toBeGreaterThan(wideP.x);

    // Stacked: the preview keeps a real height (no flex collapse) and the columns no
    // longer share horizontal space.
    await page.setViewportSize({ width: 800, height: 900 });
    await expect(preview).toBeVisible();
    const narrowP = (await preview.boundingBox())!;
    expect(narrowP.height).toBeGreaterThan(50);
    const narrowS = (await settings.boundingBox())!;
    expect(narrowS.x).toBeLessThan(narrowP.x + narrowP.width);
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
