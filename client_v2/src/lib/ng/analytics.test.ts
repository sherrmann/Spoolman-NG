import { describe, expect, it } from 'vitest';
import type { Spool, Vendor } from '$lib/types';
import type { ForkFilament, Order } from './types';
import {
	computeLowStock,
	DEFAULT_TOTAL_WEIGHT,
	DEPLETED_FRACTION,
	distinctMaterialCount,
	getColorHex,
	getFilamentName,
	getSpoolName,
	getWeightPct,
	locationBreakdown,
	lowStockNotOnOrderCount,
	materialBreakdown,
	openOrdersByFilament,
	recentSpools,
	registeredWithinDays,
	spoolStockWeight,
	staleSpools,
	topVendor,
	totalRemainingWeight,
	totalValue,
	vendorBreakdown
} from './analytics';

// Fixtures. Unlike upstream's ISpool, a Spool here only carries a filamentId — no embedded
// filament/vendor — so tests that need the join build a filament (and vendor) separately and link
// them by id, the same way the real data flows through mapSpool/mapFilament/mapVendor.

let nextVendorId = 1;
function vendor(name: string): Vendor {
	return {
		id: String(nextVendorId++),
		name,
		emptyWeight: 0,
		comment: '',
		registeredLabel: '',
		extra: {}
	};
}

let nextFilamentId = 1;
function filament(over: Partial<ForkFilament> = {}): ForkFilament {
	return {
		id: String(nextFilamentId++),
		vendorId: '',
		name: '',
		material: '',
		colors: [],
		diameter: 1.75,
		density: 1.24,
		nozzleTemp: 0,
		bedTemp: 0,
		weight: 0,
		price: 0,
		comment: '',
		registeredLabel: '',
		extra: {},
		...over
	};
}

let nextSpoolId = 1;
function spool(over: Partial<Spool> = {}): Spool {
	return {
		id: nextSpoolId++,
		filamentId: '1',
		unused: true,
		remaining: 0,
		initial: 0,
		usedWeight: 0,
		location: '',
		lot: '',
		firstUsedLabel: '',
		lastUsedLabel: '',
		registered: '2024-01-01T00:00:00Z',
		registeredLabel: '',
		archived: false,
		comment: '',
		tags: [],
		extra: {},
		...over
	};
}

function order(over: Partial<Order> = {}): Order {
	return {
		id: 1,
		orderedAt: '2026-07-10T00:00:00Z',
		lines: [],
		state: 'open',
		...over
	};
}

// spoolStockWeight

describe('spoolStockWeight', () => {
	// The remaining→initial→filament fallback this guarded against upstream now lives in mapSpool
	// (api/map.ts): `remaining` arrives already resolved, so there is no chain left for this
	// function to walk — see the module doc comment in analytics.ts.
	it('returns the resolved remaining weight', () => {
		expect(spoolStockWeight(spool({ remaining: 500 }))).toBe(500);
		expect(spoolStockWeight(spool({ remaining: 0 }))).toBe(0);
	});

	it('coerces a non-numeric remaining value to 0 instead of corrupting a sum (#377)', () => {
		// `remaining` is typed `number`, but that's a compile-time promise, not a runtime one; a
		// stray string must not silently turn `sum + spoolStockWeight(s)` into concatenation.
		const poisoned = { ...spool(), remaining: '500' as unknown as number };
		expect(spoolStockWeight(poisoned)).toBe(500);
		const garbage = { ...spool(), remaining: 'abc' as unknown as number };
		expect(spoolStockWeight(garbage)).toBe(0);
	});
});

describe('totalRemainingWeight', () => {
	it('is 0 for an empty inventory', () => {
		expect(totalRemainingWeight([])).toBe(0);
	});

	it('sums the effective stock weight across spools', () => {
		const spools = [spool({ remaining: 500 }), spool({ remaining: 800 }), spool({ remaining: 0 })];
		expect(totalRemainingWeight(spools)).toBe(1300);
	});

	// Upstream's #377 regression round-tripped through its bigint-preserving JSON reviver
	// (parseJsonWithBigIntIds) to reproduce a weight that deserializes as a *string*. This client's
	// fetch layer parses responses with the browser's own `res.json()` (api/http.ts), so that
	// specific pipeline — and the failure mode it produced — doesn't exist here. The risk
	// `spoolStockWeight`'s Number() guard defends against is still real regardless of where a bad
	// value came from, so it's exercised directly instead.
	it('sums numerically even when one spool carries a non-numeric remaining value', () => {
		const spools = [
			{ ...spool(), remaining: '0.30000000000000004' as unknown as number },
			spool({ remaining: 500 })
		];
		const total = totalRemainingWeight(spools);
		expect(typeof total).toBe('number');
		expect(total).toBeCloseTo(500.3, 6);
	});
});

describe('totalValue', () => {
	it("scales each spool's price by its remaining fraction (hand-computed)", () => {
		// 10 € spool, half used → worth 5 €.
		expect(totalValue([spool({ price: 10, initial: 1000, remaining: 500 })], [])).toBe(5);
		// 20 € spool, three quarters used → worth 5 €.
		expect(totalValue([spool({ price: 20, initial: 1000, remaining: 250 })], [])).toBe(5);
	});

	it('falls back to the filament price when the spool has none (spool price wins otherwise)', () => {
		// No spool price → the filament's 20 € applies: 20 × 250/1000 = 5 €.
		const f1 = filament({ price: 20 });
		expect(totalValue([spool({ filamentId: f1.id, initial: 1000, remaining: 250 })], [f1])).toBe(5);
		// Both set → the spool's own 10 € wins over the filament's 99 €: 10 × 500/1000 = 5 €.
		const f2 = filament({ price: 99 });
		expect(totalValue([spool({ filamentId: f2.id, price: 10, initial: 1000, remaining: 500 })], [f2])).toBe(
			5
		);
	});

	// Upstream exercised initial_weight being absent so filament.weight filled the denominator
	// (remainingFraction's ?? chain). mapSpool now performs that fallback once, before analytics
	// ever sees the spool, so what upstream called `initial_weight` and what's left here is just
	// `initial` — this checks the same 16 × 200/800 = 4 € result using the already-resolved field.
	it("uses the spool's resolved initial weight as the denominator", () => {
		const f = filament({ weight: 800 });
		expect(totalValue([spool({ filamentId: f.id, price: 16, initial: 800, remaining: 200 })], [f])).toBe(4);
	});

	it('counts a spool with no weight information as full', () => {
		expect(totalValue([spool({ price: 12 })], [])).toBe(12);
	});

	it('clamps the remaining fraction to 0..1', () => {
		// Over-full (bad data) still counts at most the full price…
		expect(totalValue([spool({ price: 10, initial: 1000, remaining: 2000 })], [])).toBe(10);
		// …and over-used never goes negative.
		expect(totalValue([spool({ price: 10, initial: 1000, remaining: -50 })], [])).toBe(0);
	});

	// Upstream's "no price anywhere" spool relied on filament.price being absent (`?? undefined`)
	// so the whole row was skipped via a null check. `Filament.price` here is a plain `number` that
	// mapFilament already defaults to 0 rather than leaving unset, so the same spool now resolves a
	// price of 0 and is multiplied through instead of filtered out — same total (0 contributed),
	// different mechanism.
	it('gives a spool without a price anywhere 0 value, and sums the rest', () => {
		const noPrice = filament(); // price defaults to 0
		const spools = [
			spool({ price: 10, initial: 1000, remaining: 500 }), // 5
			spool({ filamentId: noPrice.id, initial: 1000, remaining: 1000 }), // filament price 0 → 0
			spool({ price: 5.5 }) // full → 5.5
		];
		expect(totalValue(spools, [noPrice])).toBe(10.5);
	});

	it('is 0 for an empty inventory', () => {
		expect(totalValue([], [])).toBe(0);
	});

	it("never exceeds the inventory's full purchase value (invariant)", () => {
		const f = filament({ price: 25 });
		const spools = [
			spool({ price: 10, initial: 1000, remaining: 700 }),
			spool({ price: 30, initial: 1000, remaining: 100 }),
			spool({ filamentId: f.id, initial: 500, remaining: 400 })
		];
		const fullPurchase = 10 + 30 + 25;
		expect(totalValue(spools, [f])).toBeLessThanOrEqual(fullPurchase);
		expect(totalValue(spools, [f])).toBe(10 * 0.7 + 30 * 0.1 + 25 * 0.8);
	});
});

describe('distinctMaterialCount', () => {
	it('counts each material once, ignoring filaments without one', () => {
		const filaments = [
			filament({ material: 'PLA' }),
			filament({ material: 'PLA' }),
			filament({ material: 'PETG' }),
			filament(), // material defaults to '' → not counted
			filament({ material: '' }) // explicit empty string → not counted (same case as above here)
		];
		expect(distinctMaterialCount(filaments)).toBe(2);
	});

	it('is 0 for an empty catalog', () => {
		expect(distinctMaterialCount([])).toBe(0);
	});
});

describe('computeLowStock', () => {
	const F = 200; // fallback grams

	it('flags a filament at or below its explicit threshold, not one strictly above', () => {
		const below = filament({ id: '1', lowStockThreshold: 500, remainingWeight: 400 });
		const at = filament({ id: '2', lowStockThreshold: 500, remainingWeight: 500 });
		const above = filament({ id: '3', lowStockThreshold: 500, remainingWeight: 600 });
		const { explicit, count } = computeLowStock([below, at, above], F);
		expect(explicit.map((r) => r.filament.id)).toEqual(['1', '2']);
		expect(count).toBe(2);
	});

	it('uses the gram fallback for filaments without an explicit threshold', () => {
		const caught = filament({ id: '1', remainingWeight: 150 }); // <= 200 fallback
		const fine = filament({ id: '2', remainingWeight: 250 }); // > 200 fallback
		const { explicit, fallback } = computeLowStock([caught, fine], F);
		expect(explicit).toEqual([]);
		expect(fallback.map((r) => r.filament.id)).toEqual(['1']);
		expect(fallback[0].reason).toBe('fallback');
	});

	it('disables the fallback when fallbackG <= 0 (only explicit thresholds flag)', () => {
		const noThreshold = filament({ id: '1', remainingWeight: 10 });
		const explicitLow = filament({ id: '2', lowStockThreshold: 100, remainingWeight: 50 });
		const { explicit, fallback } = computeLowStock([noThreshold, explicitLow], 0);
		expect(fallback).toEqual([]);
		expect(explicit.map((r) => r.filament.id)).toEqual(['2']);
	});

	it('never flags a filament whose aggregate remaining weight is not populated', () => {
		expect(computeLowStock([filament({ lowStockThreshold: 500 })], F).count).toBe(0);
	});

	it('orders each section by largest shortfall first', () => {
		const small = filament({ id: '1', lowStockThreshold: 500, remainingWeight: 450 }); // short 50
		const large = filament({ id: '2', lowStockThreshold: 1000, remainingWeight: 100 }); // short 900
		const mid = filament({ id: '3', lowStockThreshold: 800, remainingWeight: 500 }); // short 300
		expect(computeLowStock([small, large, mid], F).explicit.map((r) => r.filament.id)).toEqual([
			'2',
			'3',
			'1'
		]);
	});

	it('sinks on-order filaments to the bottom of their section', () => {
		const plain = filament({ id: '1', lowStockThreshold: 500, remainingWeight: 400 }); // short 100, not ordered
		const ordered = filament({ id: '2', lowStockThreshold: 1000, remainingWeight: 100 }); // short 900, but ordered
		const onOrder = new Map([['2', { orderId: 7, orderedAt: '2026-07-10T00:00:00Z' }]]);
		expect(computeLowStock([ordered, plain], F, onOrder).explicit.map((r) => r.filament.id)).toEqual([
			'1',
			'2'
		]);
	});
});

// The always-visible Low Stock nav item's red badge counts flagged filaments that are NOT already
// on order — an on-order row is being handled, so it shouldn't nag.
describe('lowStockNotOnOrderCount', () => {
	const F = 200;

	it('counts flagged rows across both sections, excluding on-order ones', () => {
		const plain = filament({ id: '1', lowStockThreshold: 500, remainingWeight: 400 });
		const ordered = filament({ id: '2', remainingWeight: 150 }); // caught by the fallback
		const plainFallback = filament({ id: '3', remainingWeight: 100 });
		const onOrder = new Map([['2', { orderId: 7, orderedAt: '2026-07-10T00:00:00Z' }]]);
		const sections = computeLowStock([plain, ordered, plainFallback], F, onOrder);
		expect(lowStockNotOnOrderCount(sections)).toBe(2);
	});

	it('is zero when nothing is flagged, or everything flagged is already on order', () => {
		expect(lowStockNotOnOrderCount(computeLowStock([], F))).toBe(0);
		const allOrdered = filament({ id: '1', lowStockThreshold: 500, remainingWeight: 400 });
		const onOrder = new Map([['1', { orderId: 1, orderedAt: '2026-07-10T00:00:00Z' }]]);
		expect(lowStockNotOnOrderCount(computeLowStock([allOrdered], F, onOrder))).toBe(0);
	});
});

// openOrdersByFilament: mirrors upstream's lowstock/openOrders.ts, folded into this module because
// its output feeds computeLowStock's onOrder map directly (see analytics.ts's doc comment).
describe('openOrdersByFilament', () => {
	it('maps a filament to its oldest open order', () => {
		// Upstream also surfaced a shop name here; ./types's Order has no shop reference yet (this
		// fork doesn't model shops on orders), so there's nothing to carry through for that part.
		const m = openOrdersByFilament([order({ id: 5, lines: [{ id: 1, filamentId: '10', quantity: 1 }] })]);
		expect(m.get('10')).toEqual({ orderId: 5, orderedAt: '2026-07-10T00:00:00Z' });
	});

	it('prefers the oldest open order for a filament', () => {
		const m = openOrdersByFilament([
			order({ id: 5, orderedAt: '2026-07-15T00:00:00Z', lines: [{ id: 1, filamentId: '10', quantity: 1 }] }),
			order({ id: 6, orderedAt: '2026-07-01T00:00:00Z', lines: [{ id: 2, filamentId: '10', quantity: 1 }] })
		]);
		expect(m.get('10')?.orderId).toBe(6);
	});

	it('ignores arrived lines and arrived orders', () => {
		const m = openOrdersByFilament([
			order({
				id: 5,
				state: 'arrived',
				lines: [{ id: 1, filamentId: '10', quantity: 1, arrivedAt: '2026-07-11T00:00:00Z' }]
			})
		]);
		expect(m.has('10')).toBe(false);
	});
});

describe('getFilamentName', () => {
	it('prefixes the vendor name when present', () => {
		const v = vendor('Prusa');
		expect(getFilamentName(filament({ name: 'Galaxy Black', vendorId: v.id }), [v])).toBe(
			'Prusa - Galaxy Black'
		);
	});

	it('falls back to the name, then the id, without a vendor', () => {
		expect(getFilamentName(filament({ name: 'Generic PLA' }), [])).toBe('Generic PLA');
		expect(getFilamentName(filament({ id: '7', name: '' }), [])).toBe('7');
	});
});

describe('recentSpools', () => {
	it('returns most-recently-used first and excludes never-used spools', () => {
		const old = spool({ lastUsed: '2024-01-01T00:00:00Z' });
		const mid = spool({ lastUsed: '2024-03-01T00:00:00Z' });
		const recent = spool({ lastUsed: '2024-06-01T00:00:00Z' });
		const never = spool({});
		const result = recentSpools([old, never, recent, mid]);
		expect(result).toEqual([recent, mid, old]);
	});

	it('caps the list at the given limit (default 5)', () => {
		const many = Array.from({ length: 7 }, (_, i) => spool({ lastUsed: `2024-06-0${i + 1}T00:00:00Z` }));
		expect(recentSpools(many)).toHaveLength(5);
		expect(recentSpools(many, 2)).toHaveLength(2);
	});

	it('does not mutate the input array', () => {
		const input = [spool({ lastUsed: '2024-01-01T00:00:00Z' }), spool({ lastUsed: '2024-06-01T00:00:00Z' })];
		const snapshot = [...input];
		recentSpools(input);
		expect(input).toEqual(snapshot);
	});
});

describe('materialBreakdown', () => {
	it('groups by material, counts and sums weight, heaviest first', () => {
		const pla = filament({ material: 'PLA' });
		const petg = filament({ material: 'PETG' });
		const spools = [
			spool({ filamentId: pla.id, remaining: 300 }),
			spool({ filamentId: pla.id, remaining: 200 }),
			spool({ filamentId: petg.id, remaining: 900 })
		];
		expect(materialBreakdown(spools, [pla, petg])).toEqual([
			['PETG', { count: 1, weight: 900 }],
			['PLA', { count: 2, weight: 500 }]
		]);
	});

	it("buckets spools without a material under 'Unknown'", () => {
		const f = filament(); // material defaults to ''
		const result = materialBreakdown([spool({ filamentId: f.id, remaining: 100 })], [f]);
		expect(result).toEqual([['Unknown', { count: 1, weight: 100 }]]);
	});

	it('preserves the invariants: counts sum to spool count, weights sum to total', () => {
		const pla = filament({ material: 'PLA' });
		const abs = filament({ material: 'ABS' });
		const spools = [
			spool({ filamentId: pla.id, remaining: 300 }),
			spool({ filamentId: abs.id, remaining: 200 }),
			spool({ filamentId: pla.id, remaining: 400 })
		];
		const breakdown = materialBreakdown(spools, [pla, abs]);
		const countSum = breakdown.reduce((n, [, s]) => n + s.count, 0);
		const weightSum = breakdown.reduce((w, [, s]) => w + s.weight, 0);
		expect(countSum).toBe(spools.length);
		expect(weightSum).toBe(totalRemainingWeight(spools));
	});
});

describe('locationBreakdown', () => {
	it('groups by location, most-populated first, with a fallback bucket for empty', () => {
		// Distinct counts (3/2/1) so the descending sort order is actually exercised.
		const spools = [
			spool({ location: 'Shelf A' }),
			spool({ location: 'Shelf A' }),
			spool({ location: 'Shelf A' }),
			spool({ location: 'Shelf B' }),
			spool({ location: '' }),
			spool({})
		];
		expect(locationBreakdown(spools, 'No location')).toEqual([
			['Shelf A', 3],
			['No location', 2],
			['Shelf B', 1]
		]);
	});

	it('counts sum to the spool count (invariant)', () => {
		const spools = [spool({ location: 'A' }), spool({ location: 'B' }), spool({ location: 'A' })];
		const total = locationBreakdown(spools, 'None').reduce((n, [, c]) => n + c, 0);
		expect(total).toBe(spools.length);
	});
});

describe('vendorBreakdown / topVendor', () => {
	it("groups by vendor name (missing -> '?'), most-populated first", () => {
		// Distinct counts (3/2/1) AND an input order that is the reverse of the sorted order, so
		// simply dropping the sort (or a no-op comparator) is caught.
		const globex = vendor('Globex');
		const acme = vendor('Acme');
		const fGlobex = filament({ vendorId: globex.id });
		const fNoVendorA = filament();
		const fNoVendorB = filament();
		const fAcme = filament({ vendorId: acme.id });
		const spools = [
			spool({ filamentId: fGlobex.id }),
			spool({ filamentId: fNoVendorA.id }),
			spool({ filamentId: fNoVendorB.id }),
			spool({ filamentId: fAcme.id }),
			spool({ filamentId: fAcme.id }),
			spool({ filamentId: fAcme.id })
		];
		const filaments = [fGlobex, fNoVendorA, fNoVendorB, fAcme];
		expect(vendorBreakdown(spools, filaments, [globex, acme])).toEqual([
			['Acme', 3],
			['?', 2],
			['Globex', 1]
		]);
	});

	it("topVendor picks the busiest vendor, and is '-' for an empty inventory", () => {
		const acme = vendor('Acme');
		const globex = vendor('Globex');
		const fAcme = filament({ vendorId: acme.id });
		const fGlobex = filament({ vendorId: globex.id });
		const spools = [
			spool({ filamentId: fAcme.id }),
			spool({ filamentId: fGlobex.id }),
			spool({ filamentId: fAcme.id })
		];
		expect(topVendor(spools, [fAcme, fGlobex], [acme, globex])).toBe('Acme');
		expect(topVendor([], [], [])).toBe('-');
	});
});

describe('registeredWithinDays', () => {
	const now = new Date('2024-06-15T12:00:00Z');

	it('counts spools registered inside the window and excludes older ones', () => {
		const spools = [
			spool({ registered: '2024-06-10T12:00:00Z' }), // 5 days ago → in
			spool({ registered: '2024-01-01T12:00:00Z' }) // months ago → out
		];
		expect(registeredWithinDays(spools, 30, now)).toBe(1);
	});

	it('treats the exact cutoff as outside the window (strict >)', () => {
		const exactly30 = spool({ registered: new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString() });
		expect(registeredWithinDays([exactly30], 30, now)).toBe(0);
	});

	it("defaults 'now' to the current time when omitted", () => {
		// Exercises the default-parameter branch; empty input keeps it clock-independent.
		expect(registeredWithinDays([], 30)).toBe(0);
		// A spool registered in the far past is never within a 30-day window of "now".
		expect(registeredWithinDays([spool({ registered: '2000-01-01T00:00:00Z' })], 30)).toBe(0);
	});

	// Spool.registered is optional here (unlike upstream's required ISpool.registered) — a spool
	// with none has no age to compare, so it's excluded rather than crashing on `new Date(undefined)`.
	it('excludes a spool with no registered date at all', () => {
		expect(registeredWithinDays([spool({ registered: undefined })], 30, now)).toBe(0);
	});
});

describe('presentation helpers', () => {
	// Upstream normalised a raw "ff8800" / "#ff8800" string itself. `Filament.colors` here is
	// already normalised to "#rrggbb" by colorsFromApi (api/map.ts), so that part of the original
	// test no longer applies — this checks the lookup and the grey fallback instead.
	it('getColorHex reads the filament’s first colour, defaulting to grey', () => {
		const withColor = filament({ colors: ['#ff8800'] });
		expect(getColorHex(spool({ filamentId: withColor.id }), [withColor])).toBe('#ff8800');
		const noColor = filament({ colors: [] });
		expect(getColorHex(spool({ filamentId: noColor.id }), [noColor])).toBe('#555555');
		expect(getColorHex(spool({ filamentId: 'missing' }), [])).toBe('#555555');
	});

	it('getSpoolName combines vendor and name, falling back to name then id', () => {
		const acme = vendor('Acme');
		const withVendor = filament({ vendorId: acme.id, name: 'Red' });
		expect(getSpoolName(spool({ filamentId: withVendor.id }), [withVendor], [acme])).toBe('Acme - Red');
		const noVendor = filament({ name: 'Red' });
		expect(getSpoolName(spool({ filamentId: noVendor.id }), [noVendor], [])).toBe('Red');
		const unnamed = filament({ id: '77', name: '' });
		expect(getSpoolName(spool({ filamentId: unnamed.id }), [unnamed], [])).toBe('77');
	});

	it('getWeightPct clamps to 0–100 and applies the weight fallback', () => {
		expect(getWeightPct(spool({ initial: 1000, remaining: 500 }))).toBe(50);
		expect(getWeightPct(spool({ initial: 1000, remaining: 2000 }))).toBe(100); // clamped
		expect(getWeightPct(spool({ initial: 1000, remaining: 0 }))).toBe(0);
		// No weight information anywhere: mapSpool already resolved `initial` to 0, which reads as
		// a full spool rather than 0/0. (Upstream's equivalent case additionally showed
		// initial_weight winning over filament.weight as the denominator — that fallback now
		// happens inside mapSpool itself, before analytics ever sees the spool, so it isn't
		// observable at this layer any more.)
		expect(getWeightPct(spool({ initial: 0, remaining: 0 }))).toBe(100);
		expect(DEFAULT_TOTAL_WEIGHT).toBe(1000);
	});
});

// The "Gathering Dust" card lists the least-recently-used active spools. Never-used spools rank by
// their registration date (their only age signal); near-empty spools are excluded — a finished
// spool is "stale" forever but the right action is archiving it.
describe('staleSpools', () => {
	// remaining defaults to 0 in the spool() fixture above (matching mapSpool's own default), unlike
	// upstream's ISpool where an absent remaining_weight fell back to "full" — so a full/unused
	// spool has to be spelled out explicitly here rather than left to the default.
	const base = { initial: 1000, remaining: 1000 };

	it('orders by lastUsed ascending, interleaving never-used spools by registered date', () => {
		const oldNeverUsed = spool({ ...base, registered: '2023-01-01T00:00:00Z' });
		const usedLongAgo = spool({
			...base,
			lastUsed: '2024-06-01T00:00:00Z',
			registered: '2024-01-01T00:00:00Z'
		});
		const usedRecently = spool({
			...base,
			lastUsed: '2026-07-01T00:00:00Z',
			registered: '2024-01-01T00:00:00Z'
		});
		const result = staleSpools([usedRecently, oldNeverUsed, usedLongAgo]);
		expect(result.map((r) => r.spool.id)).toEqual([oldNeverUsed.id, usedLongAgo.id, usedRecently.id]);
	});

	it('flags never-used spools and dates them by registration', () => {
		const s = spool({ ...base, registered: '2023-01-01T00:00:00Z' });
		const [entry] = staleSpools([s]);
		expect(entry.neverUsed).toBe(true);
		expect(entry.staleSince).toBe('2023-01-01T00:00:00Z');
	});

	it('excludes near-empty spools', () => {
		const depleted = spool({ ...base, remaining: 10, lastUsed: '2020-01-01T00:00:00Z' }); // 1% < DEPLETED_FRACTION
		const stale = spool({ ...base, remaining: 500, lastUsed: '2024-01-01T00:00:00Z' });
		expect(staleSpools([depleted, stale]).map((r) => r.spool.id)).toEqual([stale.id]);
		expect(DEPLETED_FRACTION).toBe(0.02);
	});

	it('caps at the limit', () => {
		const spools = Array.from({ length: 8 }, (_, i) =>
			spool({ ...base, lastUsed: `2024-0${(i % 8) + 1}-01T00:00:00Z` })
		);
		expect(staleSpools(spools).length).toBe(5);
		expect(staleSpools(spools, 3).length).toBe(3);
	});

	it('does not mutate its input', () => {
		const spools = [
			spool({ ...base, lastUsed: '2024-06-01T00:00:00Z' }),
			spool({ ...base, lastUsed: '2023-06-01T00:00:00Z' })
		];
		const ids = spools.map((s) => s.id);
		staleSpools(spools);
		expect(spools.map((s) => s.id)).toEqual(ids);
	});
});
