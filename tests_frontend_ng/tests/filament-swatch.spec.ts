import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { seedFilament, unique } from "./helpers";

/**
 * The 3D-printable filament swatch (#415 step 3): the inspector's download dialog and the
 * server-wide default style setting. See docs/design/filament-parity.md ("Step 3: swatch style
 * and 3MF swatch download").
 *
 * The generator itself (lib/ng/swatch/*) has its own unit tests; what is pinned here is the
 * surface a person actually drives -- the dialog's fields, the file the download button hands
 * the browser, and the settings panel that changes the default it starts from.
 */

const SWATCH_STYLE_KEY = "swatch_style";

/** Write the `swatch_style` server setting, double-encoded like $lib/api/settings.setSetting. */
async function setSwatchStyle(request: APIRequestContext, value: string) {
  const res = await request.post(`/api/v1/setting/${SWATCH_STYLE_KEY}`, {
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify(JSON.stringify(value)),
  });
  if (!res.ok()) {
    throw new Error(
      `setting ${SWATCH_STYLE_KEY} -> ${res.status()} ${await res.text()}`,
    );
  }
}

async function getSwatchStyle(request: APIRequestContext): Promise<string> {
  const res = await request.get(`/api/v1/setting/${SWATCH_STYLE_KEY}`);
  const body = (await res.json()) as { value: string };
  try {
    return JSON.parse(body.value) as string;
  } catch {
    return "";
  }
}

async function openInspector(page: Page, filamentId: number) {
  await page.goto(`/?sel=filament:${filamentId}`, { waitUntil: "networkidle" });
  // The article number field sits above the swatch button; its presence means the inspector has
  // rendered, so the button is really absent rather than not yet loaded.
  await expect(
    page.getByRole("textbox", { name: /Article Number/i }),
  ).toBeVisible();
}

async function openSwatchDialog(page: Page, filamentId: number) {
  await openInspector(page, filamentId);
  await page.getByRole("button", { name: "3D-printable swatch" }).click();
  const dialog = page.getByRole("dialog", { name: "3D-printable swatch" });
  await expect(dialog).toBeVisible();
  return dialog;
}

test.afterEach(async ({ request }) => {
  // The server is shared with other specs; leave the default style as every other spec expects.
  await setSwatchStyle(request, "");
});

test("downloading the swatch hands the browser a real 3MF, named for the filament, and closes the dialog", async ({
  page,
  request,
}) => {
  const filament = await seedFilament(request, "SwatchDl");
  const dialog = await openSwatchDialog(page, filament.id);

  // Default style, default QR choice: the compact scan code, not a URL.
  await expect(dialog.getByRole("combobox", { name: "Style" })).toHaveValue(
    "classic",
  );
  await expect(dialog.locator("code.payload")).toHaveText(
    `WEB+SPOOLMAN:F-${filament.id}`,
  );

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    dialog.getByRole("button", { name: "Download .3mf" }).click(),
  ]);

  expect(download.suggestedFilename()).toMatch(
    new RegExp(`^swatch_classic_${filament.id}_`),
  );
  expect(download.suggestedFilename().endsWith(".3mf")).toBe(true);

  const path = await download.path();
  expect(path).toBeTruthy();
  const fs = await import("fs");
  const bytes = fs.readFileSync(path as string);

  // A 3MF is a ZIP: "PK" at the start of the local file header.
  expect(bytes.subarray(0, 2).toString("latin1")).toBe("PK");
  // Whether the entry's own file data is compressed or not, a ZIP stores every entry's name as
  // plain bytes in its local file header and again in the central directory, so the model's
  // path shows up in the raw bytes even without unzipping. This is the one fixed member every
  // style produces (see filament-parity.md's "identical for all five styles" note).
  expect(bytes.toString("latin1")).toContain("3D/3dmodel.model");

  await expect(
    page.getByRole("dialog", { name: "3D-printable swatch" }),
  ).toHaveCount(0);
});

test("choosing Keychain and the URL QR link changes the payload and the filename, and the QR choice is remembered", async ({
  page,
  request,
}) => {
  const filament = await seedFilament(request, "SwatchStyle");
  let dialog = await openSwatchDialog(page, filament.id);

  await dialog
    .getByRole("combobox", { name: "Style" })
    .selectOption("keychain");
  await dialog.getByRole("radio", { name: "URL" }).check();

  await expect(dialog.locator("code.payload")).toHaveText(
    new RegExp(`/filament/show/${filament.id}$`),
  );

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    dialog.getByRole("button", { name: "Download .3mf" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^swatch_keychain_/);

  // The choice lives in localStorage, not the dialog's own state, so it survives a reload.
  await page.reload({ waitUntil: "networkidle" });
  dialog = await openSwatchDialog(page, filament.id);
  await expect(dialog.getByRole("radio", { name: "URL" })).toBeChecked();

  // Leave the browser as later specs (and later runs of this one) find it.
  await dialog.getByRole("radio", { name: "Default" }).check();
});

test("the settings page's default swatch style is what a filament's dialog starts from", async ({
  page,
  request,
}) => {
  await page.goto("/settings", { waitUntil: "networkidle" });

  const region = page.getByRole("region", { name: "Swatches" });
  await expect(region).toBeVisible();
  // Two preview cards -- one light filament, one dark -- so both marking colours are checked.
  await expect(region.locator("svg[role=img]")).toHaveCount(2);

  await region
    .getByRole("combobox", { name: "Default swatch style" })
    .selectOption("hanger");

  await expect.poll(async () => getSwatchStyle(request)).toBe("hanger");
  // The preview cards re-render for the newly chosen style.
  await expect(region.locator("svg[role=img]")).toHaveCount(2);

  const filament = await seedFilament(request, "SwatchDefault");
  const dialog = await openSwatchDialog(page, filament.id);
  await expect(dialog.getByRole("combobox", { name: "Style" })).toHaveValue(
    "hanger",
  );
});

test("a long filament name is shortened, and the dialog says so", async ({
  page,
  request,
}) => {
  // The filament name column caps out at 64 characters, so the longest name that fits still has
  // to carry unique()'s suffix; even so it is well past the ~40 characters that made the layout
  // engine's own truncation test truncate a name on a narrower test card.
  const longName = unique("A Certainly Too Long Filament Name For The Card");
  const vendor = await request.post("/api/v1/vendor", {
    data: { name: unique("SwatchLongVendor") },
  });
  expect(vendor.ok()).toBeTruthy();
  const vendorId = ((await vendor.json()) as { id: number }).id;
  const created = await request.post("/api/v1/filament", {
    data: {
      name: longName,
      vendor_id: vendorId,
      material: "PLA",
      color_hex: "3A7BD5",
      price: 22,
      density: 1.24,
      diameter: 1.75,
      weight: 1000,
      spool_weight: 190,
    },
  });
  expect(created.ok()).toBeTruthy();
  const filamentId = ((await created.json()) as { id: number }).id;

  const dialog = await openSwatchDialog(page, filamentId);
  await expect(
    dialog.getByText("Some text was shortened to fit on the card."),
  ).toBeVisible();
});

test("two quick style changes leave the server on the later one, even if the first save is slow", async ({
  page,
  request,
}) => {
  // Two saves in flight at once could land in reverse order: the panel would show the later
  // choice while the server kept the earlier one. Holding the first save open is that race.
  let releaseFirst!: () => void;
  const firstHeld = new Promise<void>((r) => (releaseFirst = r));
  let saves = 0;
  await page.route(`**/api/v1/setting/${SWATCH_STYLE_KEY}`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    saves += 1;
    if (saves === 1) await firstHeld;
    await route.continue();
  });

  await page.goto("/settings", { waitUntil: "networkidle" });
  const select = page.getByRole("combobox", { name: "Default swatch style" });
  await select.selectOption("hanger");
  await select.selectOption("card");
  // Give a second, unordered save the chance to go out and land first.
  await page.waitForTimeout(500);
  releaseFirst();

  await expect.poll(() => getSwatchStyle(request)).toBe("card");
  await page.waitForTimeout(500);
  expect(await getSwatchStyle(request)).toBe("card");
  await expect(select).toHaveValue("card");
});
