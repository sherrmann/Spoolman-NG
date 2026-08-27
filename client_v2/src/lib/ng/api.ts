/**
 * API access for the endpoints only this fork's backend serves.
 *
 * Deliberately built on upstream's `api/http` and `api/map` rather than a parallel fetch layer:
 * base-URL resolution, the x-total-count paging header and the 401 forward-auth reload are all
 * handled there, and a second copy would drift from them.
 */
import { getJson, getList, patchJson, postJson, deleteResource, HttpError } from '$lib/api/http';
import { mapFilament, mapSpool } from '$lib/api/map';
import type { Spool } from '$lib/types';
import type {
	ArriveBody,
	ForkFilament,
	Location,
	NewOrderBody,
	Order,
	OrderPatchBody,
	Shop,
	UsageBucket,
	UsageStat
} from './types';

type Json = Record<string, unknown>;

const num = (v: unknown): number | undefined => (v === null || v === undefined ? undefined : Number(v));

function mapForkFilament(f: Json): ForkFilament {
	return {
		...mapFilament(f),
		lowStockThreshold: num(f.low_stock_threshold),
		remainingWeight: num(f.remaining_weight)
	};
}

function mapShop(s: Json): Shop {
	return {
		id: Number(s.id),
		name: String(s.name),
		homepage: s.homepage == null ? undefined : String(s.homepage),
		shipsTo: s.ships_to == null ? undefined : String(s.ships_to),
		comment: s.comment == null ? undefined : String(s.comment)
	};
}

function mapOrder(o: Json): Order {
	const lines = Array.isArray(o.lines) ? (o.lines as Json[]) : [];
	const shop = o.shop as Json | null | undefined;
	return {
		id: Number(o.id),
		orderedAt: String(o.ordered_at),
		orderNumber: o.order_number == null ? undefined : String(o.order_number),
		url: o.url == null ? undefined : String(o.url),
		comment: o.comment == null ? undefined : String(o.comment),
		shop: shop == null ? undefined : mapShop(shop),
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

/**
 * Set or clear a filament's own low-stock threshold, in grams. `null` clears it, which drops the
 * filament back to the global fallback rather than making it never-low.
 */
export async function setLowStockThreshold(filamentId: string, grams: number | null): Promise<void> {
	await patchJson(`/filament/${filamentId}`, { low_stock_threshold: grams });
}

export async function listShops(signal?: AbortSignal): Promise<Shop[]> {
	const page = await getList('/shop', {}, signal);
	return (page.items as Json[]).map(mapShop);
}

/**
 * Resolve a shop name typed into the picker to an id, creating the shop when it is new.
 *
 * Matching is case-insensitive on the trimmed name, so "Prusa" and " prusa " reuse one shop
 * rather than quietly accumulating near-duplicates. A 409 means another tab created the same
 * shop between the read and the write; refetching and matching by name is correct there, where
 * failing would lose an order the user has already filled in.
 */
export async function ensureShop(name: string): Promise<number> {
	const trimmed = name.trim();
	const matches = (shops: Shop[]) => shops.find((s) => s.name.trim().toLowerCase() === trimmed.toLowerCase());

	const existing = matches(await listShops());
	if (existing) return existing.id;

	try {
		const created = await postJson<Json>('/shop', { name: trimmed });
		return Number(created.id);
	} catch (e) {
		if (e instanceof HttpError && e.status === 409) {
			const raced = matches(await listShops());
			if (raced) return raced.id;
		}
		throw e;
	}
}

export async function createOrder(body: NewOrderBody): Promise<Order> {
	return mapOrder(await postJson<Json>('/order', body));
}

export async function getOrder(orderId: number, signal?: AbortSignal): Promise<Order> {
	return mapOrder(await getJson<Json>(`/order/${orderId}`, {}, signal));
}

export async function updateOrder(orderId: number, body: OrderPatchBody): Promise<Order> {
	return mapOrder(await patchJson<Json>(`/order/${orderId}`, body));
}

export async function deleteOrder(orderId: number): Promise<void> {
	await deleteResource(`/order/${orderId}`);
}

/**
 * Mark lines of an order arrived, optionally creating the spools they represent.
 *
 * Omitting `lines` arrives everything outstanding in full; a line with a quantity below its
 * outstanding count is a partial arrival, which the server splits.
 */
export async function arriveOrder(orderId: number, body: ArriveBody): Promise<void> {
	await postJson(`/order/${orderId}/arrive`, body);
}

/** Storage locations, for choosing where spools created on arrival should live. */
export async function listLocations(signal?: AbortSignal): Promise<Location[]> {
	const page = await getList('/location', {}, signal);
	return (page.items as Json[]).map((l) => ({ id: Number(l.id), name: String(l.name) }));
}
