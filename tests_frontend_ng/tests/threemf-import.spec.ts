import crypto from "crypto";
import fs from "fs";
import os from "os";
import path from "path";
import zlib from "zlib";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { post, seedFilament, unique } from "./helpers";

/**
 * Settings → Import / Export → "Import a sliced 3MF project" (#414 step 2). See
 * docs/design/import-export.md.
 *
 * `lib/ng/threeMfImport.ts` has its own unit tests for parsing and spool matching; this drives
 * the panel itself: picking a file, the suggested spool per row, applying usage through the same
 * `/use` call and Idempotency-Key the weigh-in uses, and the error toasts.
 */

/**
 * A minimal STORED (uncompressed) zip, built by hand from Buffers so this suite needs no zip
 * library. fflate's `unzipSync`, which the app uses to read a .3mf, accepts plain STORED entries
 * with no data descriptor, which is all this writes.
 */
function buildStoredZip(entries: { name: string; contents: string }[]): Buffer {
  const localParts: Buffer[] = [];
  const centralParts: Buffer[] = [];
  let offset = 0;
  // The DOS date/time fields are cosmetic here -- fflate does not check them -- so a fixed
  // value keeps the built bytes (and any accidental byte-for-byte comparison) deterministic.
  const dosTime = 0;
  const dosDate = 0x21;

  for (const { name, contents } of entries) {
    const nameBytes = Buffer.from(name, "utf-8");
    const dataBytes = Buffer.from(contents, "utf-8");
    const crc = zlib.crc32(dataBytes);
    const size = dataBytes.length;

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0); // local file header signature
    local.writeUInt16LE(20, 4); // version needed to extract
    local.writeUInt16LE(0, 6); // flags
    local.writeUInt16LE(0, 8); // compression method: 0 = stored
    local.writeUInt16LE(dosTime, 10);
    local.writeUInt16LE(dosDate, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(size, 18); // compressed size
    local.writeUInt32LE(size, 22); // uncompressed size
    local.writeUInt16LE(nameBytes.length, 26);
    local.writeUInt16LE(0, 28); // extra field length
    localParts.push(local, nameBytes, dataBytes);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0); // central directory header signature
    central.writeUInt16LE(20, 4); // version made by
    central.writeUInt16LE(20, 6); // version needed to extract
    central.writeUInt16LE(0, 8); // flags
    central.writeUInt16LE(0, 10); // compression method
    central.writeUInt16LE(dosTime, 12);
    central.writeUInt16LE(dosDate, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(size, 20);
    central.writeUInt32LE(size, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt16LE(0, 30); // extra field length
    central.writeUInt16LE(0, 32); // file comment length
    central.writeUInt16LE(0, 34); // disk number start
    central.writeUInt16LE(0, 36); // internal attributes
    central.writeUInt32LE(0, 38); // external attributes
    central.writeUInt32LE(offset, 42); // offset of this entry's local header
    centralParts.push(central, nameBytes);

    offset += local.length + nameBytes.length + dataBytes.length;
  }

  const centralStart = offset;
  const centralBuf = Buffer.concat(centralParts);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0); // end of central directory signature
  eocd.writeUInt16LE(0, 4); // disk number
  eocd.writeUInt16LE(0, 6); // disk with the central directory
  eocd.writeUInt16LE(entries.length, 8); // entries on this disk
  eocd.writeUInt16LE(entries.length, 10); // entries in total
  eocd.writeUInt32LE(centralBuf.length, 12);
  eocd.writeUInt32LE(centralStart, 16);
  eocd.writeUInt16LE(0, 20); // comment length

  return Buffer.concat([...localParts, centralBuf, eocd]);
}

/** Write a temporary .3mf holding just `Metadata/slice_info.config`, and return its path. */
function writeThreeMf(sliceInfoXml: string): string {
  const zip = buildStoredZip([
    { name: "Metadata/slice_info.config", contents: sliceInfoXml },
  ]);
  const file = path.join(os.tmpdir(), `${unique("threemf")}.3mf`);
  fs.writeFileSync(file, zip);
  return file;
}

/** A .3mf whose zip has no slice info at all -- just an unrelated entry. */
function writeThreeMfWithoutSliceInfo(): string {
  const zip = buildStoredZip([
    { name: "Metadata/other.txt", contents: "nothing to see here" },
  ]);
  const file = path.join(os.tmpdir(), `${unique("threemf-noslice")}.3mf`);
  fs.writeFileSync(file, zip);
  return file;
}

function sliceInfoXml(
  plates: { id: string; type: string; color: string; usedG: number }[][],
): string {
  const plateXml = plates
    .map(
      (filaments) =>
        `<plate>${filaments
          .map(
            (f) =>
              `<filament id="${f.id}" type="${f.type}" color="${f.color}" used_m="1" used_g="${f.usedG}"/>`,
          )
          .join("")}</plate>`,
    )
    .join("");
  return `<?xml version="1.0" encoding="UTF-8"?><config>${plateXml}</config>`;
}

async function patchFilament(
  api: APIRequestContext,
  id: number,
  body: unknown,
) {
  const res = await api.patch(`/api/v1/filament/${id}`, {
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify(body),
  });
  if (!res.ok())
    throw new Error(
      `PATCH /filament/${id} -> ${res.status()} ${await res.text()}`,
    );
  return res.json();
}

/** A filament of a given material and colour, and one spool of it at a known used weight. */
async function seedSpoolOf(
  api: APIRequestContext,
  prefix: string,
  material: string,
  colorHex: string,
  usedWeight: number,
) {
  const filament = await seedFilament(api, prefix);
  await patchFilament(api, filament.id, { material, color_hex: colorHex });
  const spool = await post(api, "/spool", {
    filament_id: filament.id,
    used_weight: usedWeight,
  });
  return { filamentId: filament.id, spoolId: spool.id };
}

/**
 * A random #RRGGBB, distinct from anything a fixed literal could collide with on a rerun
 * against a database earlier runs left populated.
 */
function randomHex(): string {
  return crypto.randomBytes(3).toString("hex");
}

async function spoolUsedWeight(api: APIRequestContext, spoolId: number) {
  const spool = (await (await api.get(`/api/v1/spool/${spoolId}`)).json()) as {
    used_weight: number;
  };
  return spool.used_weight;
}

async function openThreeMfSection(page: Page) {
  await page.goto("/settings", { waitUntil: "networkidle" });
  const outer = page.getByRole("region", { name: "Import / Export" });
  await expect(outer).toBeVisible();
  const threeMf = outer.getByRole("region", {
    name: "Import a sliced 3MF project",
  });
  await expect(threeMf).toBeVisible();
  return threeMf;
}

test("matches spools by colour and material and records the summed usage", async ({
  page,
  request,
}) => {
  const colorA = randomHex();
  const colorB = randomHex();
  const a = await seedSpoolOf(request, unique("ThreeMfA"), "PLA", colorA, 0);
  const b = await seedSpoolOf(request, unique("ThreeMfB"), "PETG", colorB, 0);

  const filePath = writeThreeMf(
    sliceInfoXml([
      [
        { id: "1", type: "PLA", color: `#${colorA}FF`, usedG: 10.5 },
        { id: "2", type: "PETG", color: `#${colorB}FF`, usedG: 4 },
      ],
      [{ id: "1", type: "PLA", color: `#${colorA}FF`, usedG: 2.5 }],
    ]),
  );

  const threeMf = await openThreeMfSection(page);
  await threeMf.getByLabel("Choose .3mf file").setInputFiles(filePath);

  const rows = threeMf.locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).locator(".num")).toHaveText("13 g");
  await expect(rows.nth(1).locator(".num")).toHaveText("4 g");

  const selectA = threeMf.getByLabel(/^Spool to adjust: PLA/);
  const selectB = threeMf.getByLabel(/^Spool to adjust: PETG/);
  await expect(selectA).toHaveValue(String(a.spoolId));
  await expect(selectB).toHaveValue(String(b.spoolId));

  await threeMf.getByRole("button", { name: "Apply usage" }).click();
  await expect(threeMf.getByRole("status")).toHaveText(
    "Recorded usage on 2 spool(s).",
  );
  await expect(threeMf.locator("table")).toHaveCount(0);

  expect(await spoolUsedWeight(request, a.spoolId)).toBe(13);
  expect(await spoolUsedWeight(request, b.spoolId)).toBe(4);
});

test("a failed row keeps its Idempotency-Key on retry, and only counts once", async ({
  page,
  request,
}) => {
  const colorFail = randomHex();
  const colorOk = randomHex();
  const failing = await seedSpoolOf(
    request,
    unique("ThreeMfFail"),
    "PLA",
    colorFail,
    0,
  );
  const ok = await seedSpoolOf(request, unique("ThreeMfOk"), "PLA", colorOk, 0);

  const filePath = writeThreeMf(
    sliceInfoXml([
      [
        { id: "1", type: "PLA", color: `#${colorFail}FF`, usedG: 6 },
        { id: "2", type: "PLA", color: `#${colorOk}FF`, usedG: 3 },
      ],
    ]),
  );

  const keysBySpool = new Map<number, string[]>();
  let failedOnce = false;
  await page.route("**/api/v1/spool/*/use", async (route) => {
    const url = new URL(route.request().url());
    const spoolId = Number(url.pathname.split("/").at(-2));
    const key = route.request().headers()["idempotency-key"];
    keysBySpool.set(spoolId, [...(keysBySpool.get(spoolId) ?? []), key]);
    if (spoolId === failing.spoolId && !failedOnce) {
      failedOnce = true;
      await route.fulfill({ status: 500, body: "boom" });
      return;
    }
    await route.continue();
  });

  const threeMf = await openThreeMfSection(page);
  await threeMf.getByLabel("Choose .3mf file").setInputFiles(filePath);
  await expect(threeMf.locator("tbody tr")).toHaveCount(2);

  await threeMf.getByRole("button", { name: "Apply usage" }).click();
  await expect(threeMf.getByRole("status")).toHaveText(
    "Recorded usage on 1 spool(s); 1 failed.",
  );
  await expect(threeMf.locator("tbody tr")).toHaveCount(1);

  expect(await spoolUsedWeight(request, ok.spoolId)).toBe(3);
  expect(await spoolUsedWeight(request, failing.spoolId)).toBe(0);

  await threeMf.getByRole("button", { name: "Apply usage" }).click();
  await expect(threeMf.getByRole("status")).toHaveText(
    "Recorded usage on 1 spool(s).",
  );
  await expect(threeMf.locator("table")).toHaveCount(0);

  expect(await spoolUsedWeight(request, failing.spoolId)).toBe(6);
  const failingKeys = keysBySpool.get(failing.spoolId) ?? [];
  expect(failingKeys).toHaveLength(2);
  expect(failingKeys[1]).toBe(failingKeys[0]);
});

test("a colour with no matching spool leaves the row unmatched, and Apply disabled until one is picked", async ({
  page,
  request,
}) => {
  const spool = await seedSpoolOf(
    request,
    unique("ThreeMfOther"),
    "PLA",
    randomHex(),
    0,
  );
  const filePath = writeThreeMf(
    sliceInfoXml([
      [{ id: "1", type: "ABS", color: `#${randomHex()}FF`, usedG: 7 }],
    ]),
  );

  const threeMf = await openThreeMfSection(page);
  await threeMf.getByLabel("Choose .3mf file").setInputFiles(filePath);

  const select = threeMf.getByLabel(/^Spool to adjust: ABS/);
  await expect(select).toHaveValue("");
  await expect(
    select.locator("option", { hasText: "No matching spool" }),
  ).toHaveCount(1);
  await expect(
    threeMf.getByRole("button", { name: "Apply usage" }),
  ).toBeDisabled();

  await select.selectOption(String(spool.spoolId));
  await expect(
    threeMf.getByRole("button", { name: "Apply usage" }),
  ).toBeEnabled();
});

test("a row left without a spool stays on screen after the others are recorded", async ({
  page,
  request,
}) => {
  // Dropping it would leave part of the print unrecorded while the page reports success.
  const color = randomHex();
  const matched = await seedSpoolOf(
    request,
    unique("ThreeMfKept"),
    "PLA",
    color,
    0,
  );
  const filePath = writeThreeMf(
    sliceInfoXml([
      [
        { id: "1", type: "PLA", color: `#${color}FF`, usedG: 6 },
        { id: "2", type: "ABS", color: `#${randomHex()}FF`, usedG: 3 },
      ],
    ]),
  );

  const threeMf = await openThreeMfSection(page);
  await threeMf.getByLabel("Choose .3mf file").setInputFiles(filePath);
  await expect(threeMf.getByLabel(/^Spool to adjust: PLA/)).toHaveValue(
    String(matched.spoolId),
  );
  await expect(threeMf.getByLabel(/^Spool to adjust: ABS/)).toHaveValue("");

  await threeMf.getByRole("button", { name: "Apply usage" }).click();
  await expect(threeMf.getByRole("status")).toHaveText(
    "Recorded usage on 1 spool(s).",
  );
  expect(await spoolUsedWeight(request, matched.spoolId)).toBe(6);

  const rows = threeMf.locator("tbody tr");
  await expect(rows).toHaveCount(1);
  await expect(threeMf.getByLabel(/^Spool to adjust: ABS/)).toHaveValue("");
  await expect(
    threeMf.getByRole("button", { name: "Apply usage" }),
  ).toBeDisabled();
});

test("a zip with no slice info, and a file that is not a zip at all, each show their own toast", async ({
  page,
}) => {
  const threeMf = await openThreeMfSection(page);
  const input = threeMf.getByLabel("Choose .3mf file");

  await input.setInputFiles(writeThreeMfWithoutSliceInfo());
  await expect(
    page.getByText(/This 3MF has no slice information/),
  ).toBeVisible();
  await expect(threeMf.locator("table")).toHaveCount(0);

  const notAZip = path.join(os.tmpdir(), `${unique("threemf-junk")}.3mf`);
  fs.writeFileSync(notAZip, "this is not a zip file at all");
  await input.setInputFiles(notAZip);
  await expect(page.getByText("This is not a valid 3MF file.")).toBeVisible();
  await expect(threeMf.locator("table")).toHaveCount(0);
});
