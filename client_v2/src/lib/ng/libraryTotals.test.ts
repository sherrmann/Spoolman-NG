import { describe, expect, it } from 'vitest';
import type { SpoolVM } from '$lib/utils/library';
import { totals } from './libraryTotals';

// Only the fields totals() reads.
function vm(
	spool: { remaining: number; usedWeight: number; price?: number; archived?: boolean },
	filamentPrice = 0
) {
	return { spool: { archived: false, ...spool }, filament: { price: filamentPrice } } as unknown as SpoolVM;
}

describe('totals', () => {
	it('adds up remaining, used and price, by hand', () => {
		const t = totals([
			vm({ remaining: 750, usedWeight: 250, price: 20 }), // its own price
			vm({ remaining: 1000, usedWeight: 0 }, 25), // unused, the filament's price
			vm({ remaining: 0, usedWeight: 1000, archived: true }, 18.5) // archived still counts
		]);
		expect(t).toEqual({ count: 3, remaining: 1750, used: 1250, price: 63.5 });
	});

	it('leaves out spools with no price rather than counting them as free', () => {
		const t = totals([
			vm({ remaining: 500, usedWeight: 500, price: 10 }),
			vm({ remaining: 200, usedWeight: 0 })
		]);
		expect(t.price).toBe(10);
	});

	it('has no price at all when nothing is priced', () => {
		expect(totals([vm({ remaining: 500, usedWeight: 0 })]).price).toBeNull();
	});

	it('uses a spool price of 0 as given, over the filament price', () => {
		// 0 on the spool is an explicit override (a free sample), unlike the filament's
		// unset 0; it adds nothing, but the filament's price must not be used instead.
		expect(totals([vm({ remaining: 1, usedWeight: 0, price: 0 }, 30)]).price).toBeNull();
	});

	it('does not let an over-used spool subtract from the total', () => {
		expect(totals([vm({ remaining: -40, usedWeight: 1040 })]).remaining).toBe(0);
	});

	it('is all zeros for nothing', () => {
		expect(totals([])).toEqual({ count: 0, remaining: 0, used: 0, price: null });
	});
});
