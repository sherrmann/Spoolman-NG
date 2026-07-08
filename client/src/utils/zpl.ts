// Convert a rendered label bitmap into a ZPL II graphic for Zebra label printers (#102).
//
// v1 is a faithful raster of exactly what the on-screen label renders: the label element is drawn to
// a canvas (via html-to-image, same path as "Save as image") and each pixel is thresholded to 1 bit
// and packed into a `^GFA` graphic field. This guarantees pixel parity with the preview without
// re-implementing the label layout in ZPL, and stays additive — nothing else in the print flow changes.

export interface Bitmap {
  /** RGBA bytes, row-major, 4 per pixel — the shape of a canvas ImageData.data. */
  data: Uint8ClampedArray | number[];
  width: number;
  height: number;
}

export interface ZplOptions {
  /** Luminance cutoff 0–255; a pixel darker than this becomes a black module. Default 128. */
  threshold?: number;
  /** ^FO field origin in dots. Default 0,0. */
  x?: number;
  y?: number;
}

/**
 * Pack a bitmap into a monochrome `^GFA` graphic wrapped in a minimal `^XA…^XZ` label. Pixels with
 * luminance below `threshold` (and non-transparent) become black modules; everything else is white.
 * Rows are byte-aligned (ZPL requires whole bytes per row), MSB = leftmost pixel.
 */
export function bitmapToZpl(bitmap: Bitmap, options: ZplOptions = {}): string {
  const { data, width, height } = bitmap;
  const threshold = options.threshold ?? 128;
  const x = options.x ?? 0;
  const y = options.y ?? 0;

  const bytesPerRow = Math.ceil(width / 8);
  const totalBytes = bytesPerRow * height;

  let hex = "";
  for (let row = 0; row < height; row++) {
    for (let byteIdx = 0; byteIdx < bytesPerRow; byteIdx++) {
      let byte = 0;
      for (let bit = 0; bit < 8; bit++) {
        const col = byteIdx * 8 + bit;
        if (col < width) {
          const p = (row * width + col) * 4;
          const alpha = data[p + 3];
          // Treat (semi-)transparent pixels as white so labels rendered on a transparent
          // background don't come out solid black.
          if (alpha >= 128) {
            const lum = 0.299 * data[p] + 0.587 * data[p + 1] + 0.114 * data[p + 2];
            if (lum < threshold) {
              byte |= 1 << (7 - bit);
            }
          }
        }
      }
      hex += byte.toString(16).padStart(2, "0").toUpperCase();
    }
  }

  return ["^XA", `^FO${x},${y}`, `^GFA,${totalBytes},${totalBytes},${bytesPerRow},${hex}`, "^FS", "^XZ"].join("\n");
}
