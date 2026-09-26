/**
 * Ask the server whether a typed manufacturer name probably duplicates an existing one.
 *
 * `POST /vendor/similar` (spoolman/api/v1/vendor.py) always checks for an exact match --
 * same name once case, spacing and punctuation are ignored -- and, only when the
 * `ai_feature_duplicate_check` setting is on and a decision endpoint is configured, also asks
 * the decision model for a "written differently" suggestion (spoolman/duplicates.py). Either
 * way this is a hint, never a blocker, so every failure here -- a network error, a read-only
 * user's 403, an aborted request -- degrades to "nothing to show" rather than an error the
 * caller has to handle.
 *
 * This bypasses `postJson` from $lib/api/http, which takes no `AbortSignal`, the same reason
 * `streamChat` in ./aiApi bypasses it: DuplicateHint debounces on every keystroke and has to be
 * able to cancel a request that a later keystroke has already made stale.
 */
import { API_BASE } from '$lib/api/config';
import { authHeaders } from './authToken';

export interface SimilarVendorMatch {
	id: number;
	name: string;
	/** The decision model's probability for this pick; null for an exact match. */
	probability: number | null;
}

export interface SimilarVendorResult {
	exact: SimilarVendorMatch | null;
	suggestion: SimilarVendorMatch | null;
}

const NO_MATCH: SimilarVendorResult = { exact: null, suggestion: null };

function mapMatch(raw: unknown): SimilarVendorMatch | null {
	if (!raw || typeof raw !== 'object') return null;
	const r = raw as Record<string, unknown>;
	if (typeof r.id !== 'number' || typeof r.name !== 'string') return null;
	return { id: r.id, name: r.name, probability: typeof r.probability === 'number' ? r.probability : null };
}

/**
 * `excludeId` leaves out the vendor being renamed, so it is not reported as its own duplicate;
 * omit it when the name is for a brand-new record with nothing yet to exclude.
 */
export async function similarVendor(
	name: string,
	excludeId?: number,
	signal?: AbortSignal
): Promise<SimilarVendorResult> {
	try {
		const res = await fetch(API_BASE + '/vendor/similar', {
			method: 'POST',
			headers: { 'content-type': 'application/json', ...authHeaders() },
			body: JSON.stringify({ name, exclude_id: excludeId ?? undefined }),
			signal
		});
		if (!res.ok) return NO_MATCH;
		const body = (await res.json()) as Record<string, unknown>;
		return { exact: mapMatch(body.exact), suggestion: mapMatch(body.suggestion) };
	} catch {
		// Includes an aborted request: the caller only aborts a request whose result it no
		// longer wants, so treating that the same as "nothing found" is correct, not a fallback.
		return NO_MATCH;
	}
}

/**
 * The fields `POST /filament/similar` (spoolman/api/v1/filament.py, `SimilarFilamentRequest`)
 * checks a filament-in-progress against. Everything is optional -- the same request is fired
 * while only some of the new-filament form has been filled in -- and the caller decides which
 * fields it has to hand: `vendorId` for a manufacturer picked from the catalog, `vendorName` for
 * one typed fresh.
 */
export interface FilamentSimilarityDraft {
	vendorId?: number;
	vendorName?: string;
	name?: string;
	material?: string;
	colorHex?: string;
	multiColorHexes?: string;
	diameter?: number;
}

/** Same shape as {@link SimilarVendorMatch}; `name` here is "Manufacturer Name Material". */
export type SimilarFilamentMatch = SimilarVendorMatch;

export interface SimilarFilamentResult {
	exact: SimilarFilamentMatch | null;
	suggestion: SimilarFilamentMatch | null;
}

const NO_FILAMENT_MATCH: SimilarFilamentResult = { exact: null, suggestion: null };

/**
 * `excludeId` leaves out the filament being edited, so it is not reported as its own duplicate;
 * omit it for a brand-new filament with nothing yet to exclude.
 */
export async function similarFilament(
	draft: FilamentSimilarityDraft,
	excludeId?: number,
	signal?: AbortSignal
): Promise<SimilarFilamentResult> {
	try {
		const res = await fetch(API_BASE + '/filament/similar', {
			method: 'POST',
			headers: { 'content-type': 'application/json', ...authHeaders() },
			body: JSON.stringify({
				vendor_id: draft.vendorId ?? undefined,
				vendor_name: draft.vendorName ?? undefined,
				name: draft.name ?? undefined,
				material: draft.material ?? undefined,
				color_hex: draft.colorHex ?? undefined,
				multi_color_hexes: draft.multiColorHexes ?? undefined,
				diameter: draft.diameter ?? undefined,
				exclude_id: excludeId ?? undefined
			}),
			signal
		});
		if (!res.ok) return NO_FILAMENT_MATCH;
		const body = (await res.json()) as Record<string, unknown>;
		return { exact: mapMatch(body.exact), suggestion: mapMatch(body.suggestion) };
	} catch {
		// Same reasoning as similarVendor above: an aborted request is a superseded one, not
		// a failure, so it degrades to "nothing found" like every other error here.
		return NO_FILAMENT_MATCH;
	}
}
