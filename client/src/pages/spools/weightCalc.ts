import { WeightToEnter } from "./model";

// Weight-entry math for the spool create/edit forms (#66).
//
// The backend stores a single net `used_weight`. The form lets the user enter that weight in one of
// three modes — used, remaining, or measured (gross-on-a-scale) — which are just different views of
// the same underlying number. The value the user typed in the *active* mode is the source of truth:
// used_weight is re-derived from it, so later edits to initial/spool weight recompute used_weight
// instead of silently drifting the displayed (and persisted) value.

/** Net `used_weight` (what the backend stores) for the value entered in the active mode. */
export function usedWeightFromEntered(
  mode: WeightToEnter,
  entered: number,
  filamentWeight: number,
  spoolWeight: number,
): number {
  if (mode === WeightToEnter.remaining_weight) {
    return filamentWeight - entered;
  }
  if (mode === WeightToEnter.measured_weight) {
    return filamentWeight + spoolWeight - entered;
  }
  return entered; // used_weight
}

/** The value to show for a given mode, derived from the stored `used_weight`. */
export function displayForMode(
  mode: WeightToEnter,
  usedWeight: number,
  filamentWeight: number,
  spoolWeight: number,
): number {
  if (mode === WeightToEnter.remaining_weight) {
    return filamentWeight - usedWeight;
  }
  if (mode === WeightToEnter.measured_weight) {
    return filamentWeight + spoolWeight - usedWeight;
  }
  return usedWeight;
}
