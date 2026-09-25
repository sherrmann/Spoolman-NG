/**
 * Weigh several spools in a row (#412, step 2 of docs/design/library-table-parity.md).
 *
 * After a print session: select the spools that were on the printer, put each on the scale in
 * turn, type the reading, next. The stepper is a pure reducer so the order, skipping and failure
 * handling are testable without a browser; WeighInModal is its only caller.
 */
import { parseDecimal } from '$lib/utils/numeric';

/**
 * The inspector's Adjust panel keeps its mode under this key (SpoolInspector.svelte,
 * `ADJUST_MODE_KEY`), so a mode picked in either place is what the other opens with. There it is
 * a component-local constant rather than an export, so the literal is copied here. If upstream
 * renames it the two panels would quietly keep separate modes; weighIn.test.ts reads the
 * inspector from disk and fails if the literal is no longer there.
 */
export const ADJUST_MODE_KEY = 'spoolman-v2-adjust-mode';

export type AdjustMode = 'length' | 'weight' | 'measured_weight';
export const ADJUST_MODES: readonly AdjustMode[] = ['length', 'weight', 'measured_weight'];

/** The stored mode, read the way the inspector reads it: anything unknown is `length`. */
export function parseAdjustMode(stored: string | null): AdjustMode {
	return stored === 'weight' || stored === 'measured_weight' ? stored : 'length';
}

export type Reading = { value: number } | { error: 'length' | 'weight' };

/**
 * Validate a typed reading, with the inspector's rules: a number is required, and a measured
 * gross weight cannot be negative (a consumed length or weight can: negative adds filament back).
 *
 * Stricter than the inspector in one way: it uses the app's plain-decimal parser rather than
 * parseFloat, so "12abc" or "1e2" is refused instead of read as 12 or 100.
 */
export function parseReading(raw: string, mode: AdjustMode): Reading {
	const value = parseDecimal(raw);
	if (value === null || (mode === 'measured_weight' && value < 0)) {
		return { error: mode === 'length' ? 'length' : 'weight' };
	}
	return { value };
}

/**
 * A fresh Idempotency-Key: 32 hex characters from crypto.getRandomValues.
 *
 * Not crypto.randomUUID(), which browsers only provide in a secure context, and Spoolman is
 * often served over plain HTTP on a home network. The server accepts up to 64 characters.
 */
export function newIdempotencyKey(): string {
	const bytes = crypto.getRandomValues(new Uint8Array(16));
	return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export type WeighStatus = 'updated' | 'skipped' | 'failed';

export interface WeighResult {
	id: number;
	status: WeighStatus;
	/** The server's reason, for a spool whose save failed and was then skipped. */
	error?: string;
}

export interface WeighState {
	/** Spool ids, in the order they are weighed. */
	queue: readonly number[];
	/** Position in `queue`; equal to its length once finished. */
	index: number;
	results: WeighResult[];
	/** Why the current spool's last save failed, if it did. Cleared on moving on. */
	pendingError: string | null;
}

export function startWeighIn(queue: readonly number[]): WeighState {
	return { queue, index: 0, results: [], pendingError: null };
}

export function currentId(state: WeighState): number | null {
	return state.index < state.queue.length ? state.queue[state.index] : null;
}

export function isFinished(state: WeighState): boolean {
	return state.index >= state.queue.length;
}

function advance(state: WeighState, result: WeighResult): WeighState {
	return { ...state, index: state.index + 1, results: [...state.results, result], pendingError: null };
}

/** The current spool was saved: record it and move to the next. */
export function saved(state: WeighState): WeighState {
	const id = currentId(state);
	return id === null ? state : advance(state, { id, status: 'updated' });
}

/**
 * The current spool's save failed: the connection dropped, or the spool was deleted meanwhile.
 * The stepper stays on it with the reading still typed, so a retry is one keypress and a spool
 * that cannot be saved is skipped deliberately rather than passed over unnoticed.
 */
export function failed(state: WeighState, error: string): WeighState {
	return currentId(state) === null ? state : { ...state, pendingError: error };
}

/** Move on without saving. A spool whose save had failed is recorded as failed, not skipped. */
export function skip(state: WeighState): WeighState {
	const id = currentId(state);
	if (id === null) return state;
	return advance(
		state,
		state.pendingError === null
			? { id, status: 'skipped' }
			: { id, status: 'failed', error: state.pendingError }
	);
}

/** Stop here. Spools not yet reached are left out of the results: nothing was done to them. */
export function finish(state: WeighState): WeighState {
	if (isFinished(state)) return state;
	const stopped = state.pendingError === null ? state : skip(state);
	return { ...stopped, index: stopped.queue.length, pendingError: null };
}

export function weighSummary(results: readonly WeighResult[]): Record<WeighStatus, number> {
	const out: Record<WeighStatus, number> = { updated: 0, skipped: 0, failed: 0 };
	for (const r of results) out[r.status]++;
	return out;
}
