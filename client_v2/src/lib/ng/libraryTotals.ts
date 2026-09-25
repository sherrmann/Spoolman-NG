/**
 * What the spools on screen, or the ones selected, add up to (#412 step 4).
 *
 * Pure, over the rows' view models: the footer passes the selection when there is one and the
 * rendered rows otherwise. "On screen" is exactly that, the rows loaded under expanded groups
 * on this page; the group headers' own figures are server aggregates over whole groups and a
 * different number.
 */
import type { SpoolVM } from '$lib/utils/library';

export interface Totals {
	count: number;
	/** Grams of filament left. */
	remaining: number;
	/** Grams drawn so far. */
	used: number;
	/** What the spools cost, or null when none of them has a price to add up. */
	price: number | null;
}

export function totals(vms: Iterable<SpoolVM>): Totals {
	let count = 0;
	let remaining = 0;
	let used = 0;
	let price = 0;
	let priced = false;
	for (const vm of vms) {
		count++;
		remaining += Math.max(0, vm.spool.remaining);
		used += Math.max(0, vm.spool.usedWeight);
		// A spool's own price when it has one, else its filament's, as the inspector shows it.
		// A filament price of 0 is how the API reports "not set", so it adds nothing.
		const p = vm.spool.price ?? vm.filament.price;
		if (Number.isFinite(p) && p > 0) {
			price += p;
			priced = true;
		}
	}
	return { count, remaining, used, price: priced ? price : null };
}
