import { describe, expect, it } from "vitest";
import { buildPlan } from "./plan";
import { presets } from "./presets";

/**
 * Full-plan snapshots for every preset. The committed snapshots double as
 * reviewable install recipes: a change to any generator or fragment shows up
 * here as a readable diff in the PR.
 */
describe("plan snapshots", () => {
  for (const preset of presets) {
    it(preset.id, () => {
      expect(buildPlan(preset.config)).toMatchSnapshot();
    });
  }
});
