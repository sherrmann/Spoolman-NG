import { describe, expect, it } from 'vitest';
import type { ForkFilament, Order } from './types';
import { badgeCount } from './lowStockBadge.svelte';

// The arithmetic underneath (computeLowStock/openOrdersByFilament/lowStockNotOnOrderCount) is
// covered exhaustively in analytics.test.ts. What is pinned here is the composition: the nav
// badge counts what still needs somebody's attention, which is narrower than the dashboard's
// "everything flagged" KPI, and a wrong composition would light the pill for work already done.
//
// Fixtures are built the same way analytics.test.ts builds them: a ForkFilament is a full
// domain object, so each helper fills in the fields the maths never reads.

let nextFilamentId = 1;
function filament(over: Partial<ForkFilament> = {}): ForkFilament {
	return {
		id: String(nextFilamentId++),
		vendorId: '',
		name: 'Filament',
		material: 'PLA',
		colors: [],
		diameter: 1.75,
		density: 1.24,
		nozzleTemp: 0,
		bedTemp: 0,
		weight: 1000,
		price: 0,
		comment: '',
		registeredLabel: '',
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

function line(filamentId: string, arrivedAt?: string) {
	return { id: 1, filamentId, quantity: 1, arrivedAt };
}

describe('badgeCount', () => {
	it('is 0 with nothing to count', () => {
		expect(badgeCount([], 150, [])).toBe(0);
	});

	it('counts flagged filaments that nobody has ordered', () => {
		const low = filament({ remainingWeight: 40, lowStockThreshold: 200 });
		const alsoLow = filament({ remainingWeight: 90 }); // caught by the fallback instead
		const stocked = filament({ remainingWeight: 800, lowStockThreshold: 200 });
		expect(badgeCount([low, alsoLow, stocked], 150, [])).toBe(2);
	});

	it('does not count a flagged filament that is already on an open order', () => {
		const low = filament({ remainingWeight: 40, lowStockThreshold: 200 });
		const other = filament({ remainingWeight: 40, lowStockThreshold: 200 });
		const orders = [order({ lines: [line(low.id)] })];
		expect(badgeCount([low, other], 150, orders)).toBe(1);
	});

	it('counts a filament again once its order line has arrived', () => {
		// An arrived line is no longer somebody's outstanding intent to restock: if the
		// filament is still under its threshold after the delivery, it needs attention again.
		const low = filament({ remainingWeight: 40, lowStockThreshold: 200 });
		const orders = [order({ state: 'arrived', lines: [line(low.id, '2026-07-12T00:00:00Z')] })];
		expect(badgeCount([low], 150, orders)).toBe(1);
	});

	it('treats a fallback of 0 as "no global threshold", so only explicit ones flag', () => {
		const explicit = filament({ remainingWeight: 40, lowStockThreshold: 200 });
		const wouldBeLow = filament({ remainingWeight: 40 });
		expect(badgeCount([explicit, wouldBeLow], 0, [])).toBe(1);
		expect(badgeCount([wouldBeLow], 0, [])).toBe(0);
	});

	it('ignores a filament with no remaining weight to compare', () => {
		// `remainingWeight` is the server's own aggregate over the filament's spools; absent
		// (a filament with no spools at all) there is nothing to call low.
		expect(badgeCount([filament({ lowStockThreshold: 200 })], 150, [])).toBe(0);
	});

	it('applies the global fallback to a filament with no threshold of its own', () => {
		const noThreshold = filament({ remainingWeight: 120 });
		expect(badgeCount([noThreshold], 150, [])).toBe(1);
		expect(badgeCount([noThreshold], 100, [])).toBe(0);
	});
});
