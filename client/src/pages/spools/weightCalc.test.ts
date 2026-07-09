import { describe, expect, it } from "vitest";
import { WeightToEnter } from "./model";
import { displayForMode, usedWeightFromEntered } from "./weightCalc";

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
