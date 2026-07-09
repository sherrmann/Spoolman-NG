import { ScanTarget } from "./scan";

// Pure decision logic for the scan-to-move workflow (#84), split out of the scanner component so the
// state machine can be unit-tested without a camera. In "move" mode the user scans a spool, then a
// destination location; the component turns these outcomes into effects (capture, confirm, PATCH).

export type ScanAction = "open" | "move";

export type ScanOutcome =
  /** Default mode: go to the scanned resource's page. */
  | { kind: "navigate"; path: string }
  /** Move mode, first scan: remember the spool to move. */
  | { kind: "capture_spool"; spoolId: number }
  /** Move mode, expecting a spool but something else was scanned. */
  | { kind: "need_spool" }
  /** Move mode, spool captured, expecting a location but something else was scanned. */
  | { kind: "need_location" }
  /** Move mode, both scanned: propose moving the spool to the location. */
  | { kind: "propose_move"; spoolId: number; locationId: number }
  /** Nothing to do (unrecognised code, or the same spool re-scanned while it's already selected). */
  | { kind: "ignore" };

/**
 * Decide what a scan means given the current action and move state.
 *
 * @param action     "open" (navigate) or "move" (two-scan move).
 * @param spoolId    The spool already captured in move mode, or null if none yet.
 * @param target     The parsed scan target, or null when the code wasn't recognised.
 */
export function decideScan(action: ScanAction, spoolId: number | null, target: ScanTarget | null): ScanOutcome {
  if (target === null) {
    return { kind: "ignore" };
  }
  if (action === "open") {
    return { kind: "navigate", path: target.path };
  }
  // Move mode.
  if (spoolId === null) {
    if (target.resource === "spool") {
      return { kind: "capture_spool", spoolId: Number(target.id) };
    }
    return { kind: "need_spool" };
  }
  // A spool is captured; we now want a location.
  if (target.resource === "location") {
    return { kind: "propose_move", spoolId, locationId: Number(target.id) };
  }
  if (target.resource === "spool" && Number(target.id) === spoolId) {
    // The same spool still in view — don't nag, just wait for a location.
    return { kind: "ignore" };
  }
  return { kind: "need_location" };
}
