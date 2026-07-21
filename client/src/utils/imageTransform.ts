// Client-side preparation of reference photos before upload (#88). The server stores what it is
// given and does no image processing (Pillow ships no 32-bit ARM wheels), so the browser is where
// photos get small: fit within MAX_IMAGE_DIMENSION and re-encode as WebP, falling back to JPEG
// where the browser cannot encode WebP. Re-encoding also bakes in the EXIF rotation and strips the
// metadata itself — phone photos routinely carry GPS coordinates that should not be uploaded.

export const MAX_IMAGE_DIMENSION = 1024;

export interface PreparedImage {
  blob: Blob;
  contentType: string;
}

/** Scale (width, height) to fit within max on both axes, preserving aspect ratio; never upscales. */
export function fitWithin(width: number, height: number, max: number): { width: number; height: number } {
  if (width <= max && height <= max) {
    return { width, height };
  }
  const scale = Math.min(max / width, max / height);
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

/** Decode, downscale and re-encode a picked file so it is small enough for the server's size cap. */
export async function prepareImageForUpload(file: File): Promise<PreparedImage> {
  // "from-image" applies the EXIF orientation while drawing, so portrait phone photos stay upright
  // after the metadata is stripped by re-encoding.
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  try {
    const { width, height } = fitWithin(bitmap.width, bitmap.height, MAX_IMAGE_DIMENSION);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("Canvas 2D context unavailable");
    }
    context.drawImage(bitmap, 0, 0, width, height);
    // A browser without WebP encoding support ignores the requested type and encodes PNG instead,
    // so a non-WebP result (or null) routes to the JPEG fallback rather than being sent as-is.
    let blob = await canvasToBlob(canvas, "image/webp", 0.85);
    if (!blob || blob.type !== "image/webp") {
      blob = await canvasToBlob(canvas, "image/jpeg", 0.85);
    }
    if (!blob) {
      throw new Error("Image encoding failed");
    }
    return { blob, contentType: blob.type };
  } finally {
    bitmap.close();
  }
}
