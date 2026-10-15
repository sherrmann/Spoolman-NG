import { test, expect } from "./camera";
import type { APIRequestContext, Page } from "@playwright/test";
import { seedFilament, unique } from "./helpers";

/**
 * Scan-to-Spool photo intake (client_v2/src/lib/ng/components/PhotoIntakeModal.svelte, #418).
 *
 * The vision model is STUBBED: it needs a provider and an API key, and what matters here is not
 * what the model read but where its answer goes -- into the ordinary Add-spools modal, as a lot
 * number on an existing filament or as a pre-filled new-filament form. The mapping itself is
 * unit-tested in spoolIntake.test.ts; these tests are about the wiring and the reporting.
 *
 * The button lives in the QR scanner's mode bar, so every test opens the scanner through the
 * fake-camera fixture. The camera feeds a code nothing recognises, which leaves the scanner open.
 */

// A 1 x 1 PNG: small enough to inline, real enough for createImageBitmap to decode.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

async function setFlag(request: APIRequestContext, on: boolean) {
  const res = await request.post("/api/v1/setting/ai_feature_scan_to_spool", {
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify(JSON.stringify(on)),
  });
  if (!res.ok()) throw new Error(`flag -> ${res.status()}`);
}

const blankExtraction = {
  vendor: null,
  name: null,
  material: null,
  color_hex: null,
  weight_g: null,
  spool_weight_g: null,
  diameter_mm: null,
  extruder_temp_c: null,
  bed_temp_c: null,
  lot_nr: null,
  article_number: null,
  confidence: "high",
};

async function stub(page: Page, body: unknown, status = 200) {
  await page.route("**/api/v1/ai/spool-intake/extract", (route) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    }),
  );
}

async function openScanner(page: Page) {
  await page.goto("/", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "QR Code Scanner" }).click();
  await expect(
    page.getByRole("dialog", { name: "QR Code Scanner" }),
  ).toBeVisible();
}

const intake = (page: Page) =>
  page.getByRole("dialog", { name: "Scan to Spool" });
const addSpools = (page: Page) =>
  page.getByRole("dialog").filter({ hasText: "Add spools" });

/** Scanner -> Photo -> pick a file; leaves the dialog on whatever step the stubbed answer gives. */
async function photograph(page: Page) {
  await openScanner(page);
  await page.getByRole("button", { name: "Photo" }).click();
  // Opening the dialog closes the scanner, which is what stops the camera.
  await expect(
    page.getByRole("dialog", { name: "QR Code Scanner" }),
  ).toBeHidden();
  await expect(intake(page)).toBeVisible();
  await intake(page)
    .locator('input[type="file"]')
    .setInputFiles({ name: "label.png", mimeType: "image/png", buffer: PNG });
}

test.afterEach(async ({ request }) => {
  await setFlag(request, false);
});

test("the Photo button stays hidden until an operator enables the feature", async ({
  cameraPage,
  request,
}) => {
  await setFlag(request, false);
  const page = await cameraPage(["not a spool code"]);

  await openScanner(page);

  await expect(page.getByRole("button", { name: "Move spool" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("button", { name: "Photo" })).toHaveCount(0);
});

test("a library match opens Add spools on that filament with the lot filled in", async ({
  cameraPage,
  request,
}) => {
  await setFlag(request, true);
  const filament = await seedFilament(request, "IntakeLib");
  const lot = unique("LOT");
  const page = await cameraPage(["not a spool code"]);
  await stub(page, {
    extraction: {
      ...blankExtraction,
      name: filament.name,
      material: "PLA",
      lot_nr: lot,
    },
    matches: {
      library: [
        {
          kind: "library",
          filament_id: filament.id,
          vendor: filament.vendorName,
          name: filament.name,
          material: "PLA",
          match_percent: 97,
        },
      ],
      catalog: [],
    },
  });

  await photograph(page);

  // The review lists what was read, the match first, and says the photo was not kept.
  await expect(intake(page).getByRole("radio").first()).toBeChecked();
  await expect(intake(page)).toContainText(filament.name);
  await expect(intake(page)).toContainText("is not stored");
  await intake(page).getByRole("button", { name: "Continue" }).click();

  await expect(intake(page)).toBeHidden();
  const add = addSpools(page);
  await expect(add).toBeVisible();
  // Opened ON the filament rather than on the search step.
  await expect(add).toContainText(filament.name);
  await expect(add.getByRole("textbox", { name: "Lot Nr" })).toHaveValue(lot);
});

test("the raw extraction opens a new-filament form with the values filled in", async ({
  cameraPage,
  request,
}) => {
  await setFlag(request, true);
  const name = unique("IntakeRaw");
  const page = await cameraPage(["not a spool code"]);
  await stub(page, {
    extraction: {
      ...blankExtraction,
      vendor: "Intake Test Vendor",
      name,
      material: "PETG",
      weight_g: 750,
      lot_nr: "RAW-42",
      article_number: "9900112233",
    },
    matches: { library: [], catalog: [] },
  });

  await photograph(page);

  // Nothing matched, so the raw extraction is the only choice and it is already selected.
  await expect(intake(page).getByRole("radio")).toHaveCount(1);
  await expect(intake(page).getByRole("radio")).toBeChecked();
  await intake(page).getByRole("button", { name: "Continue" }).click();

  const add = addSpools(page);
  await expect(add).toBeVisible();
  await expect(add).toContainText("Prefilled from a label photo");
  await expect(add.locator('[data-field="name"] input')).toHaveValue(name);
  await expect(add.locator('[data-field="material"] input')).toHaveValue(
    "PETG",
  );
  await expect(
    add.getByRole("textbox", { name: /Article Number/i }),
  ).toHaveValue("9900112233");
  await expect(add.getByRole("textbox", { name: "Lot Nr" })).toHaveValue(
    "RAW-42",
  );
});

test("a server with no AI endpoint configured says so instead of failing silently", async ({
  cameraPage,
  request,
}) => {
  await setFlag(request, true);
  const page = await cameraPage(["not a spool code"]);
  await stub(page, { detail: "No AI endpoint and model are configured." }, 409);

  await photograph(page);

  // Back on the first step, with the reason, so another photo can be tried once it is fixed.
  await expect(intake(page).getByRole("alert")).toContainText(
    "no AI endpoint configured",
  );
  await expect(
    intake(page).getByRole("button", { name: "Select or take a photo" }),
  ).toBeVisible();
});
