import type { WizardConfig } from "./config";
import { buildArtifacts } from "./artifacts";
import { normalizeConfig } from "./rules";
import { buildSteps } from "./steps";
import type { Plan } from "./types";

/**
 * The one entry point: raw form state in, complete personalised plan out.
 * Pure — the UI, tests and the CI render-matrix all call exactly this.
 */
export function buildPlan(input: WizardConfig): Plan {
  const { effective, warnings } = normalizeConfig(input);
  const artifacts = buildArtifacts(effective);
  const steps = buildSteps(effective, artifacts);
  return { steps, artifacts, warnings };
}
