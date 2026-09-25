import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import zlib from "zlib";
import { seedFilament } from "./helpers";

/**
 * A filament's reference photo in the inspector (#88, #415 step 2): upload, replace, remove,
 * and the browser-side resize/re-encode that happens before the bytes ever reach the server.
 *
 * See docs/design/filament-parity.md ("Step 2: reference images"). The server stores whatever
 * it is given and does no image processing, so it is the client's shrink-to-1024px-and-re-encode
 * step that these tests pin -- not just "an image appears".
 */

/** CRC-32 over a chunk's type+data, the way the PNG spec wants it in each chunk's trailer. */
function crc32(buf: Buffer): number {
  let crc = ~0;
  for (const byte of buf) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return ~crc >>> 0;
}

function pngChunk(type: string, data: Buffer): Buffer {
  const typeBuf = Buffer.from(type, "ascii");
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([len, typeBuf, data, crc]);
}

/**
 * A minimal, valid 8-bit RGB PNG: a diagonal gradient, built by hand with zlib rather than
 * shipped as a binary fixture. Good enough to stand in for a "phone photo" -- big enough
 * (2000x1200) that the browser's resize step actually has something to do.
 */
function gradientPng(width: number, height: number): Buffer {
  const signature = Buffer.from([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
  ]);
  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(width, 0);
  ihdrData.writeUInt32BE(height, 4);
  ihdrData[8] = 8; // bit depth
  ihdrData[9] = 2; // colour type: RGB, no alpha
  ihdrData[10] = 0; // compression
  ihdrData[11] = 0; // filter method
  ihdrData[12] = 0; // interlace
  const ihdr = pngChunk("IHDR", ihdrData);

  const stride = width * 3 + 1; // +1 for the per-row filter-type byte
  const raw = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y++) {
    let offset = y * stride;
    raw[offset++] = 0; // filter: none
    for (let x = 0; x < width; x++) {
      raw[offset++] = Math.floor((x / width) * 255);
      raw[offset++] = Math.floor((y / height) * 255);
      raw[offset++] = 128;
    }
  }
  const idat = pngChunk("IDAT", zlib.deflateSync(raw));
  const iend = pngChunk("IEND", Buffer.alloc(0));
  return Buffer.concat([signature, ihdr, idat, iend]);
}

async function apiFilament(request: APIRequestContext, id: number) {
  return (await (await request.get(`/api/v1/filament/${id}`)).json()) as {
    has_image?: boolean;
  };
}

async function openInspector(page: Page, filamentId: number) {
  await page.goto(`/?sel=filament:${filamentId}`, { waitUntil: "networkidle" });
  // The article number field sits above the photo section; its presence means the inspector has
  // rendered, so an absent photo below is a real absence rather than an unfinished load.
  await expect(
    page.getByRole("textbox", { name: /Article Number/i }),
  ).toBeVisible();
}

const fileInput = (page: Page) =>
  page.locator('input[type=file][accept="image/*"]');
const photoImg = (page: Page) => page.getByRole("img", { name: "Photo" });

/** Fetch the filament's stored photo from inside the page, and decode it there too, so the
 * dimensions asserted are what the browser itself would draw -- not a guess from file bytes. */
async function fetchStoredImage(page: Page, filamentId: number) {
  return page.evaluate(async (id) => {
    const res = await fetch(`/api/v1/filament/${id}/image`);
    const contentType = res.headers.get("content-type");
    const blob = await res.blob();
    const bitmap = await createImageBitmap(blob);
    return { contentType, width: bitmap.width, height: bitmap.height };
  }, filamentId);
}

test("uploading a large photo shrinks it to fit 1024px and re-encodes it off PNG", async ({
  page,
  request,
}) => {
  const filament = await seedFilament(request, "PhotoUp");
  await openInspector(page, filament.id);

  await expect(
    page.getByRole("button", { name: "Upload photo" }),
  ).toBeVisible();
  await expect(photoImg(page)).toHaveCount(0);

  // 2000x1200: the longer side (2000) must land on exactly 1024, the shorter (1200) scaled by
  // the same factor -- 1200 * (1024/2000) = 614.4, which rounds to 614.
  await fileInput(page).setInputFiles({
    name: "phone-photo.png",
    mimeType: "image/png",
    buffer: gradientPng(2000, 1200),
  });

  await expect(photoImg(page)).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "Photo saved" }),
  ).toBeVisible();

  const stored = await fetchStoredImage(page, filament.id);
  expect(["image/webp", "image/jpeg"]).toContain(stored.contentType);
  expect(stored.width).toBe(1024);
  expect(stored.height).toBe(614);

  expect((await apiFilament(request, filament.id)).has_image).toBe(true);
  await expect(
    page.getByRole("button", { name: "Replace photo" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Remove photo" }),
  ).toBeVisible();
});

test("removing a photo takes it off the filament, in the client and on the server", async ({
  page,
  request,
}) => {
  const filament = await seedFilament(request, "PhotoRemove");
  // Seeded straight through the API, not the upload button: this test is about removal, and a
  // small raw PNG is a perfectly good stand-in for whatever the client had previously encoded.
  const putRes = await request.put(`/api/v1/filament/${filament.id}/image`, {
    headers: { "Content-Type": "image/png" },
    data: gradientPng(40, 30),
  });
  expect(putRes.ok()).toBeTruthy();

  await openInspector(page, filament.id);
  await expect(photoImg(page)).toBeVisible();

  await page.getByRole("button", { name: "Remove photo" }).click();

  await expect(photoImg(page)).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Upload photo" }),
  ).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "Photo removed" }),
  ).toBeVisible();

  expect((await apiFilament(request, filament.id)).has_image ?? false).toBe(
    false,
  );
  const imgRes = await request.get(`/api/v1/filament/${filament.id}/image`);
  expect(imgRes.status()).toBe(404);
});

test("a photo added from elsewhere appears in an already-open inspector, without a reload", async ({
  page,
  request,
}) => {
  const filament = await seedFilament(request, "PhotoLive");
  await openInspector(page, filament.id);
  await expect(
    page.getByRole("button", { name: "Upload photo" }),
  ).toBeVisible();
  await expect(photoImg(page)).toHaveCount(0);

  // Added by "another client", i.e. straight through the API -- no goto/reload follows, so the
  // image can only appear here through the live filament update the endpoint broadcasts.
  const putRes = await request.put(`/api/v1/filament/${filament.id}/image`, {
    headers: { "Content-Type": "image/png" },
    data: gradientPng(50, 50),
  });
  expect(putRes.ok()).toBeTruthy();

  await expect(photoImg(page)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Replace photo" }),
  ).toBeVisible();
});

test("a file the browser cannot decode is rejected, with no upload sent", async ({
  page,
  request,
}) => {
  const filament = await seedFilament(request, "PhotoBad");
  await openInspector(page, filament.id);

  const putRequests: string[] = [];
  page.on("request", (req) => {
    if (req.method() === "PUT" && req.url().includes("/image"))
      putRequests.push(req.url());
  });

  // Random bytes, not a PNG despite the name and MIME type -- createImageBitmap must fail to
  // decode it, which is what should produce the error toast rather than a bad upload.
  const junk = Buffer.from(
    Array.from({ length: 512 }, () => Math.floor(Math.random() * 256)),
  );
  await fileInput(page).setInputFiles({
    name: "x.png",
    mimeType: "image/png",
    buffer: junk,
  });

  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Could not read that image file" }),
  ).toBeVisible();

  expect(putRequests).toHaveLength(0);
  await expect(photoImg(page)).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Upload photo" }),
  ).toBeVisible();
  expect((await apiFilament(request, filament.id)).has_image ?? false).toBe(
    false,
  );
});
