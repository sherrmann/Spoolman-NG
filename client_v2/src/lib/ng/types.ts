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
}

/** Write shape for POST /order, as built by ./orderBody. */
export interface NewOrderBody {
	ordered_at: string;
	shop_id?: number;
	order_number?: string;
	url?: string;
	lines: { filament_id: number; quantity: number; price_per_unit?: number }[];
}
