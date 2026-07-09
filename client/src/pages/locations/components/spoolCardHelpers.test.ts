import { describe, expect, it } from "vitest";
import { IFilament } from "../../filaments/model";
import { ISpool } from "../../spools/model";
import { getDisplayTotalWeight, getWeightColor, getWeightPercentage } from "./spoolCardHelpers";

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

describe("getWeightPercentage", () => {
  it("computes the remaining fraction as a percentage", () => {
    expect(getWeightPercentage(spool({ initial_weight: 1000, remaining_weight: 500 }))).toBe(50);
  });

  it("clamps above 100 and below 0", () => {
    expect(getWeightPercentage(spool({ initial_weight: 1000, remaining_weight: 2000 }))).toBe(100);
    expect(getWeightPercentage(spool({ initial_weight: 1000, remaining_weight: 0 }))).toBe(0);
  });

  it("falls back initial → filament weight → 1000 for the total", () => {
    // No initial_weight: uses filament.weight as the total.
    expect(getWeightPercentage(spool({ filament: filament({ weight: 800 }), remaining_weight: 400 }))).toBe(50);
    // No weights at all: total defaults to 1000 and remaining defaults to total → 100%.
    expect(getWeightPercentage(spool({ filament: filament() }))).toBe(100);
  });

  it("stays consistent with the dashboard's getWeightPct (no drift)", () => {
    // Same computation lives in home/analytics.ts; assert they agree on a sample.
    const s = spool({ initial_weight: 1000, remaining_weight: 123 });
    expect(getWeightPercentage(s)).toBeCloseTo(12.3, 10);
  });
});

describe("getWeightColor", () => {
  it("is red at or below 10%", () => {
    expect(getWeightColor(0)).toBe("#ff4d4f");
    expect(getWeightColor(10)).toBe("#ff4d4f");
  });

  it("is amber above 10% and at or below 25%", () => {
    expect(getWeightColor(10.1)).toBe("#faad14");
    expect(getWeightColor(25)).toBe("#faad14");
  });

  it("is green above 25%", () => {
    expect(getWeightColor(25.1)).toBe("#52c41a");
    expect(getWeightColor(100)).toBe("#52c41a");
  });
});

describe("getDisplayTotalWeight (#124)", () => {
  it("uses the spool's initial_weight when present", () => {
    expect(getDisplayTotalWeight(spool({ initial_weight: 750, filament: filament({ weight: 1000 }) }))).toBe(750);
  });

  it("falls back to the filament's nominal weight when there is no initial_weight", () => {
    expect(getDisplayTotalWeight(spool({ filament: filament({ weight: 1000 }) }))).toBe(1000);
  });

  it("is undefined when neither weight is known (subtitle then shows no weight, unlike the bar)", () => {
    expect(getDisplayTotalWeight(spool({ filament: filament() }))).toBeUndefined();
  });
});
