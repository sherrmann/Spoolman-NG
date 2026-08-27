/**
 * The scan-to-move state machine (#84), ported from client/src/utils/scanMove.ts.
 *
 * In "move" mode the user scans a spool, then scans the storage location to put it in, and the
 * caller turns the outcome into a PATCH. Pure and camera-free on purpose: the whole point of
 * splitting it out in the React client was that a two-scan flow is otherwise only testable by
 * waving physical labels at a webcam. Same reasoning holds here.
 *
 * One difference from the React original, and it is a simplification rather than a port
 * decision: React's `ScanTarget` carried a ready-made `path` string, so `navigate` outcomes
 * shipped a URL out of the pure layer. This client's `parseSpoolCode` returns `{kind, id}` and
 * leaves URL-building to `$app/paths`, so `navigate` carries the REF and the caller resolves
 * it. That keeps route knowledge in the component where SvelteKit wants it, and keeps this
 * module free of anything that needs a base path.
 */
import type { ScannedRef } from '$lib/utils/spoolCode';

/** "open" navigates to whatever was scanned; "move" runs the two-scan relocate flow. */
export type ScanAction = 'open' | 'move';

export type ScanOutcome =
	/** Default mode: go to the scanned entity. */
	| { kind: 'navigate'; ref: ScannedRef }
	/** Move mode, first scan: remember the spool being moved. */
	| { kind: 'capture_spool'; spoolId: number }
	/** Move mode, waiting for a spool but something else was scanned. */
	| { kind: 'need_spool' }
	/** Move mode, spool held, waiting for a location but something else was scanned. */
	| { kind: 'need_location' }
	/** Move mode, both scanned: propose the move. */
	| { kind: 'propose_move'; spoolId: number; locationId: number }
	/** Nothing to do: an unrecognised code, or the held spool still sitting in view. */
	| { kind: 'ignore' };

/**
 * Decide what a scan means, given the mode and the spool already held.
 *
 * @param action  'open' or 'move'.
 * @param spoolId The spool captured earlier in move mode, or null before the first scan.
 * @param ref     The parsed code, or null when it was not a Spoolman code at all.
 */
export function decideScan(action: ScanAction, spoolId: number | null, ref: ScannedRef | null): ScanOutcome {
	if (ref === null) return { kind: 'ignore' };
	if (action === 'open') return { kind: 'navigate', ref };

	// Move mode, nothing held yet: only a spool starts the flow.
	if (spoolId === null) {
		return ref.kind === 'spool' ? { kind: 'capture_spool', spoolId: ref.id } : { kind: 'need_spool' };
	}

	// A spool is held; a location completes the move.
	if (ref.kind === 'location') {
		return { kind: 'propose_move', spoolId, locationId: ref.id };
	}
	// The same spool still in the camera's view is not a mistake to complain about -- the label
	// does not move just because the user is now hunting for a shelf. Anything ELSE scanned
	// while holding a spool is worth a nudge.
	if (ref.kind === 'spool' && ref.id === spoolId) return { kind: 'ignore' };
	return { kind: 'need_location' };
}
