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
import type { FieldDef } from '$lib/api/fields';
import type {
	ArriveBody,
	ForkFilament,
	Location,
	LocationBody,
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

/**
 * Storage locations, for choosing where spools created on arrival should live.
 *
 * `/locations` (plural) is the Location *entity* registry -- rows with an id, which is what
 * `POST /order/{id}/arrive` means by `location_id`. Not to be confused with `/location`
 * (singular), which returns the distinct `Spool.location` strings and has no ids at all:
 * asking that one for entities yields a list of `{ id: NaN, name: 'undefined' }`.
 */
export async function listLocations(signal?: AbortSignal): Promise<Location[]> {
	const page = await getList('/locations', {}, signal);
	return (page.items as Json[]).map(mapLocation);
}

function mapLocation(l: Json): Location {
	return {
		id: Number(l.id),
		name: String(l.name),
		comment: l.comment == null ? undefined : String(l.comment),
		registered: l.registered == null ? undefined : String(l.registered),
		spoolCount: l.spool_count == null ? undefined : Number(l.spool_count),
		extra: (l.extra as Record<string, string> | undefined) ?? {}
	};
}

export async function getLocation(id: number, signal?: AbortSignal): Promise<Location> {
	return mapLocation(await getJson<Json>(`/locations/${id}`, {}, signal));
}

export async function createLocation(body: LocationBody): Promise<Location> {
	return mapLocation(await postJson<Json>('/locations', body));
}

export async function updateLocation(id: number, body: LocationBody): Promise<Location> {
	return mapLocation(await patchJson<Json>(`/locations/${id}`, body));
}

export async function deleteLocation(id: number): Promise<void> {
	await deleteResource(`/locations/${id}`);
}

/**
 * The registry row for a location name, created empty on first use.
 *
 * Locations on the board are `Spool.location` STRINGS; an entity row only has to exist once
 * someone wants to hang custom fields off that name. The name filter on `/locations` is a
 * partial, case-insensitive match, so the exact-name row is picked out of whatever it returns
 * rather than trusting the first hit.
 *
 * Measured, because it decides the shape of this function: the backend puts NO uniqueness
 * constraint on `location.name` -- POSTing the same name twice returns 200 twice and leaves two
 * rows. So there is no 409 to catch, and unlike ensureShop() this cannot lean on one. Two tabs
 * racing here really can produce a duplicate; findLocationByName takes the LOWEST id so that
 * every client afterwards converges on the same row rather than splitting custom-field values
 * across both. Callers that create from user input (the registry page) reject a duplicate name
 * up front, which is what keeps the race window down to genuinely concurrent writes.
 */
export async function getOrCreateLocationByName(name: string): Promise<Location> {
	return (await findLocationByName(name)) ?? (await createLocation({ name }));
}

/** The exact-name row with the lowest id, or undefined. See getOrCreateLocationByName. */
export async function findLocationByName(name: string, signal?: AbortSignal): Promise<Location | undefined> {
	const page = await getList('/locations', { name }, signal);
	return (page.items as Json[])
		.map(mapLocation)
		.filter((l) => l.name === name)
		.sort((a, b) => a.id - b.id)[0];
}

/**
 * A custom-field definition for an entity type only this fork has.
 *
 * Upstream's `$lib/api/fields` types `EntityType` as spool/filament/vendor -- those are the only
 * entities upstream has. This fork's backend also registers `location` and `printer`
 * (spoolman/extra_field_registry.py:27), and the rows it returns carry `entity_type: "location"`,
 * which that union cannot express. Widening the vendored type would be an edit upstream conflicts
 * on for no gain, so the field SHAPE is reused and only the discriminant is restated here.
 */
export type LocationFieldDef = Omit<FieldDef, 'entity_type'> & { entity_type: 'location' };

/** Custom-field DEFINITIONS for locations (`GET /field/location`). */
export async function listLocationFields(signal?: AbortSignal): Promise<LocationFieldDef[]> {
	return getJson<LocationFieldDef[]>('/field/location', {}, signal);
}

/**
 * Hand a location's field definition to upstream's `ExtraFieldInput`.
 *
 * That component's `field` prop is typed `FieldDef`, so a `LocationFieldDef` is rejected on the
 * discriminant alone. It is structurally fine: the component (and FieldGrid and EditableField
 * with it) renders from `key`, `name`, `field_type`, `choices`, `unit` and `default_value` and
 * never reads `entity_type` -- verified by grep across all three. Cast here, in one named place,
 * rather than widening the vendored union or restating the cast at every call site.
 */
export function asFieldDef(def: LocationFieldDef): FieldDef {
	return def as unknown as FieldDef;
}
