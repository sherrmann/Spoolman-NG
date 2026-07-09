import { describe, expect, it } from "vitest";
import { filamentColorObj } from "./functions";

// filamentColorObj builds the SpoolIcon colour for the filament dropdown swatch (#126). It decides
// between a single hex, a multi-colour split, or no colour — the branch that drives whether a
// swatch or the neutral "?" placeholder renders.
describe("filamentColorObj (#126)", () => {
  it("returns the single hex when there are no multi-colours", () => {
    expect(filamentColorObj("FF0000", undefined, undefined)).toBe("FF0000");
  });

  it("prefers multi-colours over the single hex, defaulting to a horizontal split", () => {
    expect(filamentColorObj("FF0000", ["FF0000", "00FF00"], "coaxial")).toEqual({
      colors: ["FF0000", "00FF00"],
      vertical: false,
    });
  });

  it("maps a longitudinal direction to a vertical split", () => {
    expect(filamentColorObj(undefined, ["FF0000", "00FF00"], "longitudinal")).toEqual({
      colors: ["FF0000", "00FF00"],
      vertical: true,
    });
  });

  it("returns undefined for a colourless filament (SpoolIcon then draws its placeholder)", () => {
    expect(filamentColorObj(undefined, undefined, undefined)).toBeUndefined();
    expect(filamentColorObj("", undefined, undefined)).toBeUndefined();
  });

  it("ignores an empty multi-colour array and falls back to the single hex", () => {
    expect(filamentColorObj("0000FF", [], "coaxial")).toBe("0000FF");
  });
});
