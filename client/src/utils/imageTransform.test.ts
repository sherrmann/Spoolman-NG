import { describe, expect, it } from "vitest";
import { fitWithin, MAX_IMAGE_DIMENSION } from "./imageTransform";

// The downscale target for reference-photo uploads (#88). Oracle: the documented contract —
// fit inside the square bound, keep the aspect ratio, never upscale, never emit a zero dimension.
// The canvas/createImageBitmap half of the module is DOM-only and covered by the e2e layer.
describe("fitWithin", () => {
  it("returns small images unchanged", () => {
    expect(fitWithin(800, 600, 1024)).toEqual({ width: 800, height: 600 });
  });

  it("returns boundary-sized images unchanged", () => {
    expect(fitWithin(1024, 1024, 1024)).toEqual({ width: 1024, height: 1024 });
  });

  it("never upscales a tiny image", () => {
    expect(fitWithin(10, 20, 1024)).toEqual({ width: 10, height: 20 });
  });

  it("scales a landscape photo down to the bound, preserving aspect ratio", () => {
    // A 4:3 4032×3024 phone photo.
    expect(fitWithin(4032, 3024, 1024)).toEqual({ width: 1024, height: 768 });
  });

  it("scales a portrait photo by its longer edge", () => {
    expect(fitWithin(3024, 4032, 1024)).toEqual({ width: 768, height: 1024 });
  });

  it("bounds both axes when both exceed the limit", () => {
    const { width, height } = fitWithin(5000, 2000, 1024);
    expect(width).toBe(1024);
    expect(height).toBe(410); // 2000 * (1024 / 5000), rounded
  });

  it("never rounds an extreme aspect ratio down to zero", () => {
    const { width, height } = fitWithin(10000, 1, 1024);
    expect(width).toBe(1024);
    expect(height).toBe(1);
  });

  it("uses the shared upload bound", () => {
    expect(MAX_IMAGE_DIMENSION).toBeGreaterThan(0);
    const { width } = fitWithin(MAX_IMAGE_DIMENSION * 2, MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION);
    expect(width).toBe(MAX_IMAGE_DIMENSION);
  });
});
