import { describe, expect, it } from "vitest";
import { IFilament } from "../pages/filaments/model";
import { ISpool } from "../pages/spools/model";
import { getSpoolEffectiveColor } from "./spoolColor";

function filament(over: Partial<IFilament> = {}): IFilament {
  return { id: 1, registered: "2024-01-01", density: 1.24, diameter: 1.75, extra: {}, ...over };
}

function spool(over: Partial<ISpool> = {}): ISpool {
  const { filament: fil, ...rest } = over;
  return {
    id: 1,
    registered: "2024-01-01T00:00:00Z",
    filament: fil ?? filament(),
    used_weight: 0,
    used_length: 0,
    archived: false,
    extra: {},
    ...rest,
  };
}

// getSpoolEffectiveColor drives every spool color swatch: color lives on the filament, so the
// swatch always reflects the parent filament's color (or the neutral placeholder when it has none).
describe("getSpoolEffectiveColor", () => {
  it("uses the filament's single color", () => {
    expect(getSpoolEffectiveColor(spool({ filament: filament({ color_hex: "00FF00" }) }))).toBe("00FF00");
  });

  it("uses the filament's multi-color", () => {
    expect(
      getSpoolEffectiveColor(
        spool({ filament: filament({ multi_color_hexes: "FF0000,00FF00", multi_color_direction: "coaxial" }) }),
      ),
    ).toEqual({ colors: ["FF0000", "00FF00"], vertical: false });
  });

  it("reads longitudinal multi-color as a vertical split", () => {
    expect(
      getSpoolEffectiveColor(
        spool({ filament: filament({ multi_color_hexes: "FF0000,0000FF", multi_color_direction: "longitudinal" }) }),
      ),
    ).toEqual({ colors: ["FF0000", "0000FF"], vertical: true });
  });

  it("is undefined when the filament has no color", () => {
    expect(getSpoolEffectiveColor(spool())).toBeUndefined();
  });
});
