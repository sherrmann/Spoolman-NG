import fs from "fs";
import os from "os";
import path from "path";
import { expect, test, type APIRequestContext } from "@playwright/test";
import { unique } from "./helpers";

/**
 * Settings → Import / Export (#414 step 1). See docs/design/import-export.md.
 *
 * The export buttons, the import form (dry run, mode, format-from-extension) and the printable
 * inventory report are what a person actually drives; `lib/ng/importExport.ts` and
 * `lib/ng/reportPrint.ts` have their own unit tests for the logic underneath.
 */

/** Write a temporary file for `setInputFiles` and return its path. */
function writeTemp(name: string, contents: string): string {
  const file = path.join(os.tmpdir(), `${unique("ie")}-${name}`);
  fs.writeFileSync(file, contents);
  return file;
}

async function post(api: APIRequestContext, endpoint: string, body: unknown) {
  const res = await api.post(`/api/v1${endpoint}`, {
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify(body),
  });
  if (!res.ok()) {
    throw new Error(`POST ${endpoint} -> ${res.status()} ${await res.text()}`);
  }
  return res.json();
}

async function vendorsNamed(api: APIRequestContext, name: string) {
  return (await (
    await api.get(`/api/v1/vendor?name=${encodeURIComponent(name)}`)
  ).json()) as unknown[];
}

async function filamentsNamed(api: APIRequestContext, name: string) {
  return (await (
    await api.get(`/api/v1/filament?name=${encodeURIComponent(name)}`)
  ).json()) as unknown[];
}

test("exporting manufacturers downloads real data, as both CSV and JSON", async ({
  page,
  request,
}) => {
  const vendorName = unique("IeVendor");
  await post(request, "/vendor", { name: vendorName });

  await page.goto("/settings", { waitUntil: "networkidle" });
  const section = page.getByRole("region", { name: "Import / Export" });
  await expect(section).toBeVisible();

  const [csvDownload] = await Promise.all([
    page.waitForEvent("download"),
    section.getByRole("button", { name: "Manufacturers · CSV" }).click(),
  ]);
  expect(csvDownload.suggestedFilename()).toBe("spoolman-vendors.csv");
  const csvPath = await csvDownload.path();
  expect(csvPath).toBeTruthy();
  expect(fs.readFileSync(csvPath as string, "utf-8")).toContain(vendorName);

  const [jsonDownload] = await Promise.all([
    page.waitForEvent("download"),
    section.getByRole("button", { name: "Manufacturers · JSON" }).click(),
  ]);
  expect(jsonDownload.suggestedFilename()).toBe("spoolman-vendors.json");
  const jsonPath = await jsonDownload.path();
  const rows = JSON.parse(fs.readFileSync(jsonPath as string, "utf-8")) as {
    name: string;
  }[];
  expect(Array.isArray(rows)).toBe(true);
  expect(rows.some((r) => r.name === vendorName)).toBe(true);
});

test("a dry run changes nothing, and turning it off actually creates the row", async ({
  page,
  request,
}) => {
  const vendorName = unique("IeDryRun");
  const csvPath = writeTemp(
    "vendor.csv",
    `name,comment\n${vendorName},seeded\n`,
  );

  await page.goto("/settings", { waitUntil: "networkidle" });
  const section = page.getByRole("region", { name: "Import / Export" });
  await section.getByRole("combobox", { name: "Data" }).selectOption("vendors");
  await section.getByLabel("Choose file").setInputFiles(csvPath);

  const status = section.getByRole("status");
  await expect(
    section.getByRole("checkbox", { name: "Dry run" }),
  ).toBeChecked();
  await section.getByRole("button", { name: "Validate" }).click();
  await expect(status).toHaveText("Dry run — Created 1, updated 0, skipped 0.");
  expect(await vendorsNamed(request, vendorName)).toHaveLength(0);

  await section.getByRole("checkbox", { name: "Dry run" }).uncheck();
  await section.getByRole("button", { name: "Import" }).click();
  await expect(status).toHaveText("Created 1, updated 0, skipped 0.");
  expect(await vendorsNamed(request, vendorName)).toHaveLength(1);
  // The file is spent once imported: in "create" mode, which ignores ids, a second click would
  // insert every row again, so the button waits for a new file.
  await expect(section.getByRole("button", { name: "Import" })).toBeDisabled();
});

test("a bad row fails the whole file and lists the row error, leaving nothing imported", async ({
  page,
  request,
}) => {
  const goodName = unique("IeGood");
  const badName = unique("IeBad");
  // The good row leaves vendor.id blank (optional); the bad row points it at a vendor that does
  // not exist, which is the one thing that should sink the whole file.
  const csvPath = writeTemp(
    "filaments.csv",
    `name,material,density,diameter,vendor.id\n${goodName},PLA,1.24,1.75,\n${badName},PLA,1.24,1.75,999999\n`,
  );

  await page.goto("/settings", { waitUntil: "networkidle" });
  const section = page.getByRole("region", { name: "Import / Export" });
  await section
    .getByRole("combobox", { name: "Data" })
    .selectOption("filaments");
  await section.getByRole("checkbox", { name: "Dry run" }).uncheck();
  await section.getByLabel("Choose file").setInputFiles(csvPath);

  const status = section.getByRole("status");
  await section.getByRole("button", { name: "Import" }).click();
  await expect(status).toContainText("Import failed");
  await expect(status).toContainText("vendor with id 999999");

  expect(await filamentsNamed(request, goodName)).toHaveLength(0);
  expect(await filamentsNamed(request, badName)).toHaveLength(0);
});

test("the format follows the picked file's extension", async ({ page }) => {
  const jsonPath = writeTemp("vendors.json", "[]");

  await page.goto("/settings", { waitUntil: "networkidle" });
  const section = page.getByRole("region", { name: "Import / Export" });
  await section.getByLabel("Choose file").setInputFiles(jsonPath);

  await expect(section.getByRole("combobox", { name: "Format" })).toHaveValue(
    "json",
  );
});

test("the printed report shows the heading and the seeded material, and cleans up after printing", async ({
  page,
  request,
}) => {
  const material = unique("RPT").toUpperCase();
  const location = unique("IeShelf");
  const vendor = await post(request, "/vendor", {
    name: unique("IeReportVendor"),
  });
  const filament = await post(request, "/filament", {
    name: unique("IeReportFilament"),
    vendor_id: (vendor as { id: number }).id,
    material,
    color_hex: "3A7BD5",
    price: 20,
    density: 1.24,
    diameter: 1.75,
    weight: 1000,
    spool_weight: 190,
  });
  await post(request, "/spool", {
    filament_id: (filament as { id: number }).id,
    location,
  });

  await page.goto("/settings", { waitUntil: "networkidle" });
  const section = page.getByRole("region", { name: "Import / Export" });

  // Stub window.print rather than letting the real print dialog open, and capture the built
  // report's text at the moment printReport calls it -- before the fallback timeout, and before
  // afterprint below removes the root.
  await page.evaluate(() => {
    (window as unknown as { print: () => void }).print = () => {
      (window as unknown as { __reportText?: string }).__reportText =
        document.querySelector(".inventory-report-root")?.textContent ?? "";
    };
  });

  await section.getByRole("button", { name: "Print report" }).click();
  await expect
    .poll(() =>
      page.evaluate(
        () => (window as unknown as { __reportText?: string }).__reportText,
      ),
    )
    .toBeTruthy();

  const reportText = await page.evaluate(
    () => (window as unknown as { __reportText?: string }).__reportText,
  );
  expect(reportText).toContain("Spoolman Inventory Report");
  expect(reportText).toContain(material);

  await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
  await expect(page.locator(".inventory-report-root")).toHaveCount(0);
});
