import { describe, expect, it } from "vitest";
import { suggestDensityForMaterial } from "./materialDensities";

// Issue #54: suggest a density for a known material, case-insensitively, and undefined otherwise.
describe("suggestDensityForMaterial", () => {
  it("matches known materials case-insensitively and trims whitespace", () => {
    expect(suggestDensityForMaterial("PLA")).toBe(1.24);
    expect(suggestDensityForMaterial("pla")).toBe(1.24);
    expect(suggestDensityForMaterial("  PETG ")).toBe(1.27);
    expect(suggestDensityForMaterial("abs")).toBe(1.04);
  });

  it("returns undefined for unknown or empty input", () => {
    expect(suggestDensityForMaterial("Unobtainium")).toBeUndefined();
    expect(suggestDensityForMaterial("")).toBeUndefined();
    expect(suggestDensityForMaterial(undefined)).toBeUndefined();
    expect(suggestDensityForMaterial(null)).toBeUndefined();
  });
});
