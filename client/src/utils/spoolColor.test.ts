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

// getSpoolEffectiveColor drives every spool color swatch (#74): the spool's own override wins
// wholesale, otherwise the filament's color, otherwise undefined (neutral placeholder).
describe("getSpoolEffectiveColor (#74)", () => {
  it("falls back to the filament color when the spool has no override", () => {
    expect(getSpoolEffectiveColor(spool({ filament: filament({ color_hex: "00FF00" }) }))).toBe("00FF00");
  });

  it("prefers the spool's single-color override over the filament color", () => {
    expect(getSpoolEffectiveColor(spool({ color_hex: "FF0000", filament: filament({ color_hex: "00FF00" }) }))).toBe(
      "FF0000",
    );
  });

  it("prefers a spool multi-color override, replacing a single-color filament", () => {
    expect(
      getSpoolEffectiveColor(
        spool({
          multi_color_hexes: "FF0000,0000FF",
          multi_color_direction: "longitudinal",
          filament: filament({ color_hex: "00FF00" }),
        }),
      ),
    ).toEqual({ colors: ["FF0000", "0000FF"], vertical: true });
  });

  it("uses the filament's multi-color when the spool has no override", () => {
    expect(
      getSpoolEffectiveColor(
        spool({ filament: filament({ multi_color_hexes: "FF0000,00FF00", multi_color_direction: "coaxial" }) }),
      ),
    ).toEqual({ colors: ["FF0000", "00FF00"], vertical: false });
  });

  it("is undefined when neither spool nor filament has a color", () => {
    expect(getSpoolEffectiveColor(spool())).toBeUndefined();
  });
});
