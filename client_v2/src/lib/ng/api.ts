/**
 * API access for the endpoints only this fork's backend serves.
 *
 * Deliberately built on upstream's `api/http` and `api/map` rather than a parallel fetch layer:
 * base-URL resolution, the x-total-count paging header and the 401 forward-auth reload are all
 * handled there, and a second copy would drift from them.
 */
import { getJson, getList } from '$lib/api/http';
import { mapFilament, mapSpool } from '$lib/api/map';
import type { Spool } from '$lib/types';
import type { ForkFilament, Order, UsageBucket, UsageStat } from './types';

type Json = Record<string, unknown>;

const num = (v: unknown): number | undefined => (v === null || v === undefined ? undefined : Number(v));

function mapForkFilament(f: Json): ForkFilament {
	return {
		...mapFilament(f),
		lowStockThreshold: num(f.low_stock_threshold),
		remainingWeight: num(f.remaining_weight)
	};
}

function mapOrder(o: Json): Order {
	const lines = Array.isArray(o.lines) ? (o.lines as Json[]) : [];
	return {
		id: Number(o.id),
		orderedAt: String(o.ordered_at),
		orderNumber: o.order_number == null ? undefined : String(o.order_number),
		url: o.url == null ? undefined : String(o.url),
		state: o.state === 'arrived' ? 'arrived' : 'open',
		lines: lines.map((l) => ({
			id: Number(l.id),
			// String, to match the id type upstream's Filament uses: CockroachDB ids exceed
			// what a JS number represents exactly, so they are never narrowed to one.
			filamentId: String(l.filament_id),
			quantity: Number(l.quantity),
			pricePerUnit: num(l.price_per_unit),
			arrivedAt: l.arrived_at == null ? undefined : String(l.arrived_at)
		}))
	};
}

/** Every non-archived spool. The dashboard aggregates over all of them, so it does not page. */
export async function listAllSpools(signal?: AbortSignal): Promise<Spool[]> {
	const page = await getList('/spool', { allow_archived: 'false' }, signal);
	return (page.items as Json[]).map(mapSpool);
}

export async function listAllFilaments(signal?: AbortSignal): Promise<ForkFilament[]> {
	const page = await getList('/filament', {}, signal);
	return (page.items as Json[]).map(mapForkFilament);
}

export async function listOrders(signal?: AbortSignal): Promise<Order[]> {
	const page = await getList('/order', {}, signal);
	return (page.items as Json[]).map(mapOrder);
}

export async function listVendorCount(signal?: AbortSignal): Promise<number> {
	const page = await getList('/vendor', { limit: 1, offset: 0 }, signal);
	return page.total;
}

export async function usageStats(bucket: UsageBucket, signal?: AbortSignal): Promise<UsageStat[]> {
	const rows = await getJson<Json[]>('/stats/usage', { bucket }, signal);
	return rows.map((r) => ({
		period: String(r.period),
		consumedWeight: Number(r.consumed_weight),
		cost: Number(r.cost)
	}));
}

/**
 * The global low-stock fallback, in grams. Settings are stored as JSON-encoded strings, and a
 * value of 0 or less disables the fallback entirely -- so a filament is only ever "low" against
 * its own threshold. Returns 0 when the setting is unreadable, which disables it the same way.
 */
export async function lowStockFallbackG(signal?: AbortSignal): Promise<number> {
	try {
		const setting = await getJson<Json>('/setting/low_stock_fallback_g', {}, signal);
		const parsed = Number(JSON.parse(String(setting.value)));
		return Number.isFinite(parsed) ? parsed : 0;
	} catch {
		return 0;
	}
}
