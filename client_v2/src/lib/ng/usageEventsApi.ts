/**
 * A spool's persisted usage/adjustment log (#50), an endpoint only this fork's backend serves.
 *
 * Built on upstream's `api/http` for the same reasons `lib/ng/api.ts` is -- base-URL resolution,
 * the bearer credential and the 401 handling all live there -- and mapped from the wire's
 * snake_case to camelCase the same way `usageStats` is.
 */
import { getJson } from '$lib/api/http';

export interface SpoolUsageEvent {
	id: number;
	spoolId: number;
	/** ISO timestamp in UTC; the wire carries the trailing `Z`. */
	time: string;
	/** One of `use`, `measure`, `update`. */
	eventType: string;
	/** Change applied to used_weight, in grams; positive means consumed. */
	delta: number;
	/** The raw gross weight recorded with a `measure` event, in grams. */
	measuredWeight?: number;
	comment?: string;
}

type Json = Record<string, unknown>;

/**
 * Every event recorded against one spool, newest first.
 *
 * Deliberately unbounded, unlike the React client's `limit=50`. The endpoint has no default
 * limit of its own, and a spool weighed regularly over a year or two would silently lose its
 * oldest measurements off the left of the chart -- which is precisely the part that shows a
 * trend. One spool's log is small enough that there is nothing here worth paging.
 */
export async function listSpoolEvents(spoolId: number, signal?: AbortSignal): Promise<SpoolUsageEvent[]> {
	const rows = await getJson<Json[]>(`/spool/${spoolId}/events`, {}, signal);
	return rows.map((r) => ({
		id: Number(r.id),
		spoolId: Number(r.spool_id),
		time: String(r.time),
		eventType: String(r.event_type),
		delta: Number(r.delta),
		measuredWeight: r.measured_weight == null ? undefined : Number(r.measured_weight),
		comment: r.comment == null ? undefined : String(r.comment)
	}));
}
