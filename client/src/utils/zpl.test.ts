import { describe, expect, it } from "vitest";
import { Bitmap, bitmapToZpl } from "./zpl";

// Build an RGBA bitmap from a 2D grid of booleans (true = black opaque pixel).
function grid(rows: boolean[][]): Bitmap {
  const height = rows.length;
  const width = rows[0].length;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let r = 0; r < height; r++) {
    for (let c = 0; c < width; c++) {
      const p = (r * width + c) * 4;
      const v = rows[r][c] ? 0 : 255;
      data[p] = v;
      data[p + 1] = v;
      data[p + 2] = v;
      data[p + 3] = 255;
    }
  }
  return { data, width, height };
}

describe("bitmapToZpl", () => {
  it("wraps the graphic in a minimal ^XA…^XZ label with a ^GFA field", () => {
    const zpl = bitmapToZpl(grid([[true]]));
    expect(zpl.startsWith("^XA")).toBe(true);
    expect(zpl.trimEnd().endsWith("^XZ")).toBe(true);
    expect(zpl).toContain("^GFA,");
    expect(zpl).toContain("^FO0,0");
  });

  it("packs 8 pixels into one byte, MSB = leftmost, black = 1", () => {
    // 10000000 → 0x80
    const zpl = bitmapToZpl(grid([[true, false, false, false, false, false, false, false]]));
    expect(zpl).toContain("^GFA,1,1,1,80");
    // 00000001 → 0x01
    const zpl2 = bitmapToZpl(grid([[false, false, false, false, false, false, false, true]]));
    expect(zpl2).toContain("^GFA,1,1,1,01");
  });

  it("byte-aligns each row: a 9-px-wide image uses 2 bytes per row", () => {
    const row = [true, ...Array(8).fill(false)]; // 9 wide
    const zpl = bitmapToZpl(grid([row]));
    // bytesPerRow = 2, totalBytes = 2; first byte 0x80 (leftmost black), padding byte 0x00.
    expect(zpl).toContain("^GFA,2,2,2,8000");
  });

  it("emits one row of hex per image row", () => {
    const zpl = bitmapToZpl(
      grid([
        [true, false, false, false, false, false, false, false],
        [false, false, false, false, false, false, false, true],
      ]),
    );
    // 2 rows × 1 byte = 2 bytes: 80 then 01.
    expect(zpl).toContain("^GFA,2,2,1,8001");
  });

  it("treats transparent pixels as white regardless of colour", () => {
    const width = 1;
    const height = 1;
    const data = new Uint8ClampedArray([0, 0, 0, 0]); // black but fully transparent
    const zpl = bitmapToZpl({ data, width, height });
    expect(zpl).toContain("^GFA,1,1,1,00");
  });

  it("honours a custom origin and threshold", () => {
    const width = 1;
    const height = 1;
    const data = new Uint8ClampedArray([200, 200, 200, 255]); // light grey
    // Default threshold 128 → white (00); threshold 210 → dark (80).
    expect(bitmapToZpl({ data, width, height })).toContain(",1,1,1,00");
    expect(bitmapToZpl({ data, width, height }, { threshold: 210, x: 5, y: 7 })).toContain("^FO5,7");
    expect(bitmapToZpl({ data, width, height }, { threshold: 210 })).toContain(",1,1,1,80");
  });
});
