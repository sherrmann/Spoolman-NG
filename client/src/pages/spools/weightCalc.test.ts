import { describe, expect, it } from "vitest";
import { WeightToEnter } from "./model";
import { correctOverweight, displayForMode, usedWeightFromEntered } from "./weightCalc";

// #66: the three weight modes are views of one net used_weight. These tests pin the round-trip and,
// crucially, the regression: changing initial/spool weight after entering a value must preserve the
// entered value and re-derive used_weight — not drift it.

const FW = 1000; // filament (full-spool net) weight
const SW = 200; // empty spool weight

describe("weightCalc", () => {
  it.each([WeightToEnter.used_weight, WeightToEnter.remaining_weight, WeightToEnter.measured_weight])(
    "round-trips entered → used_weight → displayed for mode %i",
    (mode) => {
      const entered = 350;
      const used = usedWeightFromEntered(mode, entered, FW, SW);
      expect(displayForMode(mode, used, FW, SW)).toBeCloseTo(entered, 6);
    },
  );

  it("maps each mode to the right used_weight", () => {
    expect(usedWeightFromEntered(WeightToEnter.used_weight, 400, FW, SW)).toBe(400);
    // remaining 600 on a 1000 g spool ⇒ 400 used
    expect(usedWeightFromEntered(WeightToEnter.remaining_weight, 600, FW, SW)).toBe(400);
    // measured 800 gross (1000 + 200 − used) ⇒ 400 used
    expect(usedWeightFromEntered(WeightToEnter.measured_weight, 800, FW, SW)).toBe(400);
  });

  it("preserves a measured reading when the spool weight is corrected (the #66 regression)", () => {
    // User measures 800 g gross with an assumed 200 g spool ⇒ used 400.
    const entered = 800;
    const usedBefore = usedWeightFromEntered(WeightToEnter.measured_weight, entered, FW, 200);
    expect(usedBefore).toBe(400);

    // They correct the spool weight to 300 g. The scale still reads 800, so the entered value is kept
    // and used_weight is re-derived — it must change, and the measured display must stay 800.
    const usedAfter = usedWeightFromEntered(WeightToEnter.measured_weight, entered, FW, 300);
    expect(usedAfter).toBe(500);
    expect(displayForMode(WeightToEnter.measured_weight, usedAfter, FW, 300)).toBe(800);
  });

  it("leaves used-mode entry unaffected by initial/spool weight", () => {
    // Used weight is absolute: changing the spool/filament weight must not move it.
    expect(usedWeightFromEntered(WeightToEnter.used_weight, 250, 1000, 200)).toBe(250);
    expect(usedWeightFromEntered(WeightToEnter.used_weight, 250, 900, 350)).toBe(250);
  });
});

// #61: a spool physically heavier than its theoretical weight (measured > filament+spool, or
// remaining > filament weight) used to submit a negative used_weight, which the backend rejects
// with a 422. The correction mirrors the backend measure() path: raise initial_weight to match
// physical reality and zero the usage.
describe("correctOverweight (#61)", () => {
  it("is a no-op for non-negative used weight", () => {
    expect(correctOverweight(200, 1000)).toEqual({ used: 200, initial: 1000 });
    expect(correctOverweight(0, 1000)).toEqual({ used: 0, initial: 1000 });
  });

  it("absorbs a measured-above-gross deficit into initial_weight", () => {
    // Measured 1250 on a 1000 g filament with a 200 g spool: used = 1000+200-1250 = -50.
    expect(correctOverweight(-50, 1000)).toEqual({ used: 0, initial: 1050 });
  });

  it("absorbs a remaining-above-nominal deficit into initial_weight", () => {
    // Remaining 1100 entered on a 1000 g filament: used = 1000-1100 = -100.
    expect(correctOverweight(-100, 1000)).toEqual({ used: 0, initial: 1100 });
  });
});
