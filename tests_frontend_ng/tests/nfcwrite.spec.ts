import { expect, test, type Page } from "@playwright/test";
import { seedSpool, unique } from "./helpers";

/**
 * Writing a spool's data onto an NFC tag (client_v2/src/lib/ng/components/NfcWriteModal.svelte).
 *
 * These tests run where neither radio exists: the CI host has no NFC reader attached, and
 * headless Chromium has no Web NFC. That is not a limitation to work around -- it is the
 * ordinary desktop case, and it is the state most likely to be got wrong, because the dialog
 * has to explain which of two unavailable things is missing and still leave the one route that
 * needs no hardware working. The server-write and browser-write paths cannot be exercised
 * without hardware and are covered by unit tests over the codec and the API wrapper instead.
 */

const dialog = (page: Page) => page.getByRole("dialog", { name: "Encode Spool to NFC Tag" });

async function openWriter(page: Page, spoolId: number) {
  await page.goto(`/?sel=spool:${spoolId}`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Encode to NFC" }).click();
  await expect(dialog(page)).toBeVisible();
}

test("the encode control is offered from a spool's tag section", async ({ page, request }) => {
  const { spoolId } = await seedSpool(request, "NfcOpen", unique("Bench"));
  await openWriter(page, spoolId);
});

test("the preview shows what will be written, from the filament", async ({ page, request }) => {
  // The preview is the only chance to notice you are about to write the wrong spool's data, so
  // it has to carry real values rather than placeholders.
  const { spoolId } = await seedSpool(request, "NfcPreview", unique("Bench"));
  await openWriter(page, spoolId);

  const panel = dialog(page);
  await expect(panel).toContainText("PLA");
  await expect(panel).toContainText("1.75 mm");
  await expect(panel).toContainText("1000 g");
});

test("with no reader and no Web NFC, it names the reader rather than misdirecting", async ({
  page,
  request,
}) => {
  // The other message ends "Use the Server mode with a connected reader", which is advice to
  // somewhere equally broken when there is no reader either. Getting this backwards sends the
  // user in a circle, which is why it is asserted rather than eyeballed.
  const { spoolId } = await seedSpool(request, "NfcNoHw", unique("Bench"));
  await openWriter(page, spoolId);

  await expect(dialog(page)).toContainText("No NFC reader detected");
  await expect(dialog(page)).not.toContainText("Use the Server mode");
});

test("the raw-binary download works with no hardware at all", async ({ page, request }) => {
  // The whole point of this route: a desktop or iOS user, whose browser has no Web NFC and whose
  // host has no reader, can still get the exact bytes out to an external tool.
  const { spoolId } = await seedSpool(request, "NfcDownload", unique("Bench"));
  await openWriter(page, spoolId);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    dialog(page).getByRole("button", { name: "Download Raw Binary" }).click(),
  ]);

  expect(download.suggestedFilename()).toBe(`spool-${spoolId}-tigertag.bin`);
  // 144 bytes is the TigerTag NTAG213 payload (pages 4-39). A short file would still "download"
  // and still look like success, so the length is the assertion that means anything here.
  const path = await download.path();
  const { statSync } = await import("node:fs");
  expect(statSync(path).size).toBe(144);
});

test("closing the dialog leaves the spool page working", async ({ page, request }) => {
  // The dialog aborts an in-flight write on close; a bug there would surface as a page that
  // stops responding rather than as an error.
  const { spoolId } = await seedSpool(request, "NfcClose", unique("Bench"));
  await openWriter(page, spoolId);

  await dialog(page).getByRole("button", { name: "Cancel" }).click();
  await expect(dialog(page)).toBeHidden();
  await expect(page.getByRole("button", { name: "Encode to NFC" })).toBeVisible();
});
