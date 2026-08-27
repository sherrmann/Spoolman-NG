/**
 * Domain types for entities that exist only in this fork.
 *
 * Upstream's `$lib/types` covers spools, filaments and vendors; it has no notion of purchase
 * orders, usage history or low-stock thresholds, because upstream's backend has none. These
 * extend rather than replace it, so a fork page can pass a `ForkFilament` to any upstream
 * component that takes a `Filament`.
 */
import type { Filament } from '$lib/types';

export interface ForkFilament extends Filament {
	/** Per-filament low-stock threshold in grams; undefined falls back to the global setting. */
	lowStockThreshold?: number;
	/** Server-computed total remaining weight across this filament's spools, in grams. */
	remainingWeight?: number;
}

export interface OrderLine {
	id: number;
	filamentId: string;
	quantity: number;
	pricePerUnit?: number;
	/** ISO timestamp; undefined means the line is still outstanding. */
	arrivedAt?: string;
}

export interface Order {
	id: number;
	orderedAt: string;
	orderNumber?: string;
	url?: string;
	comment?: string;
	/** The shop this was placed with, when one was recorded. */
	shop?: Shop;
	lines: OrderLine[];
	/** Derived server-side: 'open' while any line is un-arrived. */
	state: 'open' | 'arrived';
}

/** One time bucket from GET /stats/usage. */
export interface UsageStat {
	/** Bucket start label: YYYY-MM-DD (day/week), YYYY-MM (month) or YYYY (year). */
	period: string;
	consumedWeight: number;
	cost: number;
}

export type UsageBucket = 'day' | 'week' | 'month' | 'year';

/** A shop an order was placed with. Fork-only, like orders themselves. */
export interface Shop {
	id: number;
	name: string;
	homepage?: string;
	shipsTo?: string;
	comment?: string;
}

/**
 * Write shape for POST /order, as built by ./orderBody.
 *
 * Snake_case and numeric ids because this is the wire contract (see OrderParameters in
 * spoolman/api/v1/models.py), not a domain type -- everything the components hold uses the
 * camelCase, string-id `Order` above.
 */
export interface NewOrderBody {
	ordered_at: string;
	shop_id?: number;
	order_number?: string;
	url?: string;
	comment?: string;
	lines: { filament_id: number; quantity: number; price_per_unit?: number }[];
}

/**
 * Write shape for PATCH /order/{id}.
 *
 * Deliberately unlike NewOrderBody: blank optional fields are sent as explicit `null` because
 * that is how the API clears them, where the create path omits them instead. And `lines`
 * replaces the entire line set whenever it is present -- the API has no per-line endpoint -- so
 * an edit must resend every line, arrived ones included.
 */
export interface OrderPatchBody {
	shop_id: number | null;
	ordered_at: string;
	order_number: string | null;
	url: string | null;
	comment: string | null;
	lines: OrderPatchLine[];
}

/** One line as sent on a PATCH: an already-arrived line resends its arrived_at verbatim. */
export interface OrderPatchLine {
	filament_id: number;
	quantity: number;
	price_per_unit?: number;
	arrived_at?: string;
}

/** Write shape for POST /order/{id}/arrive. */
export interface ArriveBody {
	/** Omitted entirely means "arrive everything outstanding, in full". */
	lines?: { line_id: number; quantity?: number }[];
	create_spools: boolean;
	location_id?: number;
}

/**
 * A Location ENTITY row (`/api/v1/locations`). Fork-only (#103).
 *
 * Not to be confused with `Spool.location`, which is a plain `String(64)` column holding a name.
 * There is no foreign key between the two: this registry exists so a location name can carry
 * custom fields and a scannable identity, and a spool is matched to it by string equality. That
 * is also why upstream's /dashboard can be the location BOARD without knowing this table exists
 * -- it only ever reads and writes the spool's own string.
 *
 * `spoolCount` is a server-computed aggregate present on the list and detail endpoints only.
 */
export interface Location {
	id: number;
	name: string;
	comment?: string;
	registered?: string;
	spoolCount?: number;
	/** Custom-field values, JSON-encoded per key, exactly as the API stores them. */
	extra: Record<string, string>;
}

/** Write shape for POST /locations and PATCH /locations/{id}. */
export interface LocationBody {
	name?: string;
	comment?: string | null;
	extra?: Record<string, string>;
}
