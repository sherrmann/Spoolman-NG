/**
 * Pure, framework-free dashboard analytics — ported from client/src/pages/home/analytics.ts and
 * client/src/pages/lowstock/openOrders.ts so the KPI/inventory math can be unit-tested against
 * hand-computed oracles rather than through a rendered component.
 *
 * The upstream client works directly against the REST shape (snake_case, nullable weights, a
 * `Spool` that embeds its whole `filament`). This client's domain types (`$lib/types`, `./types`)
 * are already mapped: camelCase, string filament/vendor ids, and — the part that reshapes several
 * functions below — a `Spool` that only carries a `filamentId`, plus `remaining`/`initial` fields
 * that `mapSpool` (see `$lib/api/map.ts`) has *already* resolved: `remaining` is `remaining_weight
 * ?? 0` and `initial` is `initial_weight ?? filament.weight ?? 0`. Upstream's three-level
 * remaining→initial→filament fallback chain therefore collapses to a field read in most of these
 * functions; where that changes a function's shape or a test's meaning, a comment says so at the
 * call site.
 *
 * Because a `Spool` no longer carries its filament (or a filament its vendor), every function that
 * needs that join takes the relevant `ForkFilament[]` / `Vendor[]` alongside the spools, and builds
 * a lookup internally — the same join `stores/inventory.svelte.ts` does with `filamentById` /
 * `vendorById`, just without depending on that store so this stays pure and testable.
 */
import type { Spool, Vendor } from '$lib/types';
import type { ForkFilament, Order } from './types';

function byId<T extends { id: string }>(items: T[]): Map<string, T> {
	const out = new Map<string, T>();
	for (const item of items) out.set(item.id, item);
	return out;
}

// A spool whose resolved initial weight is 0 (mapSpool found no initial_weight AND no filament
// weight to fall back to) falls back to this nominal total so its remaining fraction/percentage
// reads as "full" rather than divide-by-zero — the same nominal fallback upstream used, though its
// exact value no longer affects the outcome (see effectiveWeights below): once initial is 0 there
// is no weight information to be a fraction OF, so the ratio is defined to be 1 regardless of what
// the two sides of it are.
export const DEFAULT_TOTAL_WEIGHT = 1000;

export interface MaterialStat {
	count: number;
	weight: number;
}

/**
 * Effective stock weight of one spool. Upstream's version walked remaining_weight ?? initial_weight
 * ?? filament.weight ?? 0 to survive a spool whose remaining weight was simply never recorded;
 * `mapSpool` now does that resolution once, up front, so `remaining` is always populated and there
 * is no chain left to walk here.
 *
 * What still matters is the defensive coercion (upstream #377): this client's fetch layer parses
 * responses with the browser's own `res.json()` (see `api/http.ts`), not a bigint-preserving
 * reviver, so it can't reproduce the specific failure that bit upstream — an oversized whole-number
 * weight silently coming back as a *string* (their CockroachDB id rule, #69, applied to a weight
 * column). But `remaining` is only a `number` at the type level, not a runtime guarantee, and every
 * aggregate below sums with `+`, which silently becomes concatenation the moment one operand is a
 * string. The same `Number()` + `Number.isFinite` guard costs nothing and closes that class of bug
 * no matter where a bad value would come from.
 */
export function spoolStockWeight(spool: Spool): number {
	const numeric = Number(spool.remaining);
	return Number.isFinite(numeric) ? numeric : 0;
}

/** Total remaining filament weight across all spools (headline KPI). */
export function totalRemainingWeight(spools: Spool[]): number {
	return spools.reduce((sum, s) => sum + spoolStockWeight(s), 0);
}

/**
 * `{ total, remaining }` a fraction/percentage helper can divide safely. Mirrors upstream's
 * `initial_weight ?? filament.weight ?? DEFAULT_TOTAL_WEIGHT` / `remaining_weight ?? total`, but
 * since `mapSpool` already resolved the filament fallback into `initial`, the only case left to
 * handle here is "no weight information anywhere" (`initial <= 0`), which reads as a full spool.
 */
function effectiveWeights(s: Spool): { total: number; remaining: number } {
	if (s.initial > 0) return { total: s.initial, remaining: s.remaining };
	return { total: DEFAULT_TOTAL_WEIGHT, remaining: DEFAULT_TOTAL_WEIGHT };
}

/** Remaining stock fraction of one spool; no weight information anywhere counts as a full spool. */
function remainingFraction(s: Spool): number {
	const { total, remaining } = effectiveWeights(s);
	return remaining / total;
}

/** Effective full-spool price of one spool: its own price, falling back to its filament's. */
function effectiveSpoolPrice(s: Spool, filamentById: Map<string, ForkFilament>): number | undefined {
	return s.price ?? filamentById.get(s.filamentId)?.price;
}

/**
 * Estimated value of the filament currently in stock. Each spool contributes its effective price
 * (spool price, else filament price) scaled by its remaining fraction, so a half-used spool counts
 * half its price. Spools with no weight information count as full.
 *
 * Upstream skipped a spool whose price resolved to `null` ("no price anywhere"). `Filament.price`
 * here is a plain `number` that `mapFilament` already defaults to 0 rather than leaving unset, so
 * that case can no longer produce `undefined` from the filament side — it contributes 0 through the
 * ordinary multiplication instead of being filtered out, with the same total either way. The
 * `undefined` branch below only still fires for a spool whose `filamentId` isn't in `filaments` at
 * all (a spool orphaned by a deleted filament).
 */
export function totalValue(spools: Spool[], filaments: ForkFilament[]): number {
	const filamentById = byId(filaments);
	return spools.reduce((sum, s) => {
		const price = effectiveSpoolPrice(s, filamentById);
		if (price == null) return sum;
		return sum + price * Math.min(1, Math.max(0, remainingFraction(s)));
	}, 0);
}

/** Number of distinct materials across the filament catalog; filaments without one don't count. */
export function distinctMaterialCount(filaments: ForkFilament[]): number {
	return new Set(filaments.map((f) => f.material).filter((m): m is string => !!m)).size;
}

/** One filament's oldest open order, once known — see `openOrdersByFilament` below. */
export interface OnOrderInfo {
	orderId: number;
	orderedAt: string;
}

export interface LowStockRow {
	filament: ForkFilament;
	remaining: number;
	threshold: number;
	/** Why this row is listed: its own threshold, or the global gram fallback. Drives section separation. */
	reason: 'explicit' | 'fallback';
	/** Oldest open order for this filament, if any — drives the "Ordered" pill and the sink-to-bottom sort. */
	onOrder?: OnOrderInfo;
}

export interface LowStockSections {
	/** Rows flagged by their own lowStockThreshold; largest shortfall first, on-order rows last. */
	explicit: LowStockRow[];
	/** Rows flagged only by the global gram fallback; same ordering. */
	fallback: LowStockRow[];
	/** Total flagged filaments across both sections — the dashboard KPI badge count. */
	count: number;
}

/** On-order rows sink to the bottom of their section; otherwise largest shortfall first. */
function compareLowStockRows(a: LowStockRow, b: LowStockRow): number {
	const ao = a.onOrder ? 1 : 0;
	const bo = b.onOrder ? 1 : 0;
	if (ao !== bo) return ao - bo;
	return b.threshold - b.remaining - (a.threshold - a.remaining);
}

/**
 * Merged per-filament Low Stock. A filament is flagged when its server-computed aggregate
 * `remainingWeight` is at or below its own `lowStockThreshold` when set, else at or below the
 * global fallback `fallbackG` (absolute grams; a value <= 0 disables the fallback). Explicit-
 * threshold and fallback-caught rows are returned in separate sections so the UI can show WHY each
 * is listed; within each, on-order filaments sink last.
 *
 * Upstream read an `on_order` field the server precomputes directly onto each filament. `ForkFilament`
 * carries no such field (see `./types`), so the on-order lookup instead comes in as a map — build one
 * with `openOrdersByFilament(orders)` and pass it here; omit it to treat nothing as on order.
 */
export function computeLowStock(
	filaments: ForkFilament[],
	fallbackG: number,
	onOrderByFilament: Map<string, OnOrderInfo> = new Map()
): LowStockSections {
	const explicit: LowStockRow[] = [];
	const fallback: LowStockRow[] = [];
	for (const f of filaments) {
		if (f.remainingWeight == null) continue;
		const hasExplicit = f.lowStockThreshold != null;
		const threshold = hasExplicit ? (f.lowStockThreshold as number) : fallbackG;
		if (threshold <= 0) continue; // fallback disabled, or a nonsensical explicit 0
		if (f.remainingWeight > threshold) continue;
		const row: LowStockRow = {
			filament: f,
			remaining: f.remainingWeight,
			threshold,
			reason: hasExplicit ? 'explicit' : 'fallback',
			onOrder: onOrderByFilament.get(f.id)
		};
		(hasExplicit ? explicit : fallback).push(row);
	}
	explicit.sort(compareLowStockRows);
	fallback.sort(compareLowStockRows);
	return { explicit, fallback, count: explicit.length + fallback.length };
}

/**
 * Count of Low Stock rows across both sections that are NOT already on order — drives the red badge
 * on the always-visible "Low Stock" nav item. On-order rows are already being handled, so they
 * don't contribute to the "needs attention" count.
 */
export function lowStockNotOnOrderCount(sections: LowStockSections): number {
	return [...sections.explicit, ...sections.fallback].filter((r) => !r.onOrder).length;
}

/**
 * Map each on-order filament to the OLDEST open order that contains it, for the Low Stock
 * "Ordered" pill and its order link, and for `computeLowStock`'s sink-to-bottom sort.
 *
 * Upstream's version (lowstock/openOrders.ts) returned `{ order_id, shop_name }`, dropping
 * `ordered_at` from its output because that field arrived on the filament separately (via the
 * server-computed `on_order` this fork's `ForkFilament` doesn't have — see `computeLowStock`
 * above). `Order` here (./types) has no shop reference at all yet, so there is no shop name to
 * carry through; `orderedAt` is kept instead of dropped, since it's the one piece both this
 * function and `computeLowStock`'s onOrder-gated sort actually have a use for.
 */
export function openOrdersByFilament(orders: Order[]): Map<string, OnOrderInfo> {
	const oldest = new Map<string, OnOrderInfo>();
	for (const order of orders) {
		if (order.state !== 'open') continue;
		for (const line of order.lines) {
			if (line.arrivedAt) continue;
			const prev = oldest.get(line.filamentId);
			if (!prev || new Date(order.orderedAt).getTime() < new Date(prev.orderedAt).getTime()) {
				oldest.set(line.filamentId, { orderId: order.id, orderedAt: order.orderedAt });
			}
		}
	}
	return oldest;
}

/**
 * Human label for a filament: "Vendor - Name", falling back to the name or id.
 *
 * `Filament.name` is a plain `string` here — `mapFilament` already defaults a nameless filament to
 * a placeholder ('(unnamed filament)') rather than leaving it unset, so the id fallback below is
 * only reachable when a caller (or, as in this module's tests, a fixture) builds a `ForkFilament`
 * with an empty name directly, bypassing that mapper. Kept anyway: it costs nothing and protects
 * against exactly that.
 */
export function getFilamentName(filament: ForkFilament, vendors: Vendor[]): string {
	const base = filament.name || filament.id;
	const vendor = vendors.find((v) => v.id === filament.vendorId);
	return vendor ? `${vendor.name} - ${base}` : base;
}

/** The most-recently-used spools, newest first, capped at `limit`. Does not mutate the input. */
export function recentSpools(spools: Spool[], limit = 5): Spool[] {
	return spools
		.filter((s) => s.lastUsed)
		.map((s) => [new Date(s.lastUsed as string).getTime(), s] as const)
		.sort((a, b) => b[0] - a[0])
		.slice(0, limit)
		.map(([, s]) => s);
}

/** Count + total weight grouped by material (default "Unknown"), heaviest group first. */
export function materialBreakdown(spools: Spool[], filaments: ForkFilament[]): [string, MaterialStat][] {
	const filamentById = byId(filaments);
	const map: Record<string, MaterialStat> = {};
	spools.forEach((s) => {
		const mat = filamentById.get(s.filamentId)?.material || 'Unknown';
		if (!map[mat]) map[mat] = { count: 0, weight: 0 };
		map[mat].count++;
		map[mat].weight += spoolStockWeight(s);
	});
	return Object.entries(map).sort((a, b) => b[1].weight - a[1].weight);
}

/** Spool count grouped by location (empty → `noLocationLabel`), most-populated first. */
export function locationBreakdown(spools: Spool[], noLocationLabel: string): [string, number][] {
	const map: Record<string, number> = {};
	spools.forEach((s) => {
		const loc = s.location || noLocationLabel;
		map[loc] = (map[loc] ?? 0) + 1;
	});
	return Object.entries(map).sort((a, b) => b[1] - a[1]);
}

/** Spool count grouped by vendor name (unknown → "?"), most-populated first. */
export function vendorBreakdown(
	spools: Spool[],
	filaments: ForkFilament[],
	vendors: Vendor[]
): [string, number][] {
	const filamentById = byId(filaments);
	const vendorById = byId(vendors);
	const map: Record<string, number> = {};
	spools.forEach((s) => {
		const filament = filamentById.get(s.filamentId);
		const name = (filament && vendorById.get(filament.vendorId)?.name) || '?';
		map[name] = (map[name] ?? 0) + 1;
	});
	return Object.entries(map).sort((a, b) => b[1] - a[1]);
}

/** The vendor owning the most spools, or "-" when there are no spools. */
export function topVendor(spools: Spool[], filaments: ForkFilament[], vendors: Vendor[]): string {
	return vendorBreakdown(spools, filaments, vendors)[0]?.[0] ?? '-';
}

/** Number of spools registered within the last `days` days relative to `now`. */
export function registeredWithinDays(spools: Spool[], days: number, now: Date = new Date()): number {
	const cutoff = now.getTime() - days * 24 * 60 * 60 * 1000;
	// `Spool.registered` is optional here (unlike upstream's required `ISpool.registered`), since a
	// spool the client only has a partial view of could lack it; such a spool has no age to compare,
	// so it never counts as "within" the window.
	return spools.filter((s) => s.registered != null && new Date(s.registered).getTime() > cutoff).length;
}

/**
 * "#rrggbb" swatch for a spool, preferring its filament's first colour, defaulting to a mid-grey
 * when none is set or the filament can't be found. Multi-colour is out of scope for this
 * single-swatch chart — same as upstream.
 *
 * Upstream normalised a raw `color_hex` string ("ff8800" or "#ff8800") itself. `Filament.colors`
 * here already comes out of `colorsFromApi` (`api/map.ts`) pre-normalised to "#rrggbb" strings, so
 * there is nothing left to strip/re-prefix.
 */
export function getColorHex(spool: Spool, filaments: ForkFilament[]): string {
	const filament = filaments.find((f) => f.id === spool.filamentId);
	return filament?.colors[0] ?? '#555555';
}

/** Human label for a spool: "Vendor - Name", falling back to the filament name or id. */
export function getSpoolName(spool: Spool, filaments: ForkFilament[], vendors: Vendor[]): string {
	const filament = filaments.find((f) => f.id === spool.filamentId);
	// Defensive only: a spool whose filament has been deleted out from under it (see
	// `inventory.svelte.ts`'s `removeVendor`, which leaves filaments in place but nulls vendorId —
	// filaments themselves are never silently orphaned the same way, but nothing guarantees it here).
	if (!filament) return String(spool.filamentId);
	return getFilamentName(filament, vendors);
}

/** Remaining-weight percentage (0–100, clamped) for a progress bar. */
export function getWeightPct(spool: Spool): number {
	const { total, remaining } = effectiveWeights(spool);
	return Math.max(0, Math.min(100, (remaining / total) * 100));
}

/** Age labels turn amber past this many days unused, red past STALE_ALERT_DAYS. */
export const STALE_WARN_DAYS = 90;
export const STALE_ALERT_DAYS = 180;

/** Below this remaining fraction a spool counts as finished, not stale. */
export const DEPLETED_FRACTION = 0.02;

export interface StaleSpool {
	spool: Spool;
	/** The date the staleness is measured from: lastUsed, or registered when never used. */
	staleSince: string;
	neverUsed: boolean;
}

/**
 * The least-recently-used active spools, oldest first. Never-used spools rank by their
 * registration date — a two-year-old unopened spool outranks one printed months ago. Near-empty
 * spools are excluded: a finished spool is "stale" forever, but the right action there is
 * archiving, not drying.
 *
 * Unlike upstream, this no longer takes a filament list: `remainingFraction` only needs `initial`/
 * `remaining`, and `mapSpool` has already resolved those from the filament where relevant (see the
 * module doc comment above).
 */
export function staleSpools(spools: Spool[], limit = 5): StaleSpool[] {
	return spools
		.filter((s) => remainingFraction(s) >= DEPLETED_FRACTION)
		.map((s) => ({ spool: s, staleSince: s.lastUsed ?? s.registered ?? '', neverUsed: !s.lastUsed }))
		.sort((a, b) => new Date(a.staleSince).getTime() - new Date(b.staleSince).getTime())
		.slice(0, limit);
}
