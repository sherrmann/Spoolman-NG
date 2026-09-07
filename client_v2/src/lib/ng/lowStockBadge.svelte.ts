/**
 * The count behind the red pill on the "Low Stock" nav tab (#417).
 *
 * It is a module singleton rather than per-component state because `NavTabs` renders twice --
 * once in the desktop row of the top bar and once in its mobile row (see TopBar.svelte) -- and
 * both are mounted at all times on every page. Per-instance state would mean two identical
 * loads at startup and two more on every live event; sharing one cache means the pill costs
 * three requests for the life of the tab, whatever the user navigates to.
 *
 * The count is the same one the Low Stock page's own header maths produces: flagged filaments
 * that are NOT already on an open order (`lowStockNotOnOrderCount`), which is React parity --
 * a filament somebody has already reordered needs no further attention, so it must not keep the
 * pill lit. That deliberately differs from the dashboard KPI, which counts everything flagged.
 *
 * Kept free of any DOM or component API so the maths below is importable in vitest.
 */
import { isAbortError } from '$lib/api/http';
import { live } from '$lib/api/live';
import { computeLowStock, lowStockNotOnOrderCount, openOrdersByFilament } from './analytics';
import { listAllFilaments, listOrders, lowStockFallbackG } from './api';
import type { ForkFilament, Order } from './types';

/** Live events arrive in bursts (one per spool of a filament); coalesce them, as the pages do. */
const REFRESH_DEBOUNCE_MS = 400;

/**
 * The badge number for one snapshot of the data: how many low-stock filaments are still
 * waiting on somebody. Pure, so the semantics can be pinned without a fetch or a component.
 */
export function badgeCount(filaments: ForkFilament[], fallbackG: number, orders: Order[]): number {
	return lowStockNotOnOrderCount(computeLowStock(filaments, fallbackG, openOrdersByFilament(orders)));
}

class LowStockBadge {
	/**
	 * Filaments needing attention. 0 until the first load lands, so nothing flashes on startup;
	 * the badge hides at 0, so "not loaded yet" and "nothing is low" look the same on purpose.
	 */
	count = $state(0);

	/**
	 * Whether a load has been asked for at all -- done, in flight, or failed -- which is what
	 * makes `ensure()` a no-op after the first caller.
	 *
	 * Deliberately NOT `$state`: `ensure()` is called from a component
	 * `$effect`, and a reactive read there would re-run that effect when the first load lands --
	 * tearing down the live subscriptions and their websockets and rebuilding them for nothing.
	 */
	private requested = false;
	/** The in-flight load, so `refresh()` can supersede it and a second `ensure()` can skip. */
	private controller: AbortController | null = null;
	/** How many mounted badges want the live subscriptions; the last one out turns them off. */
	private subscribers = 0;
	private offLive: (() => void)[] = [];
	private timer: ReturnType<typeof setTimeout> | null = null;

	/** Load once. A second caller, on the page's other `NavTabs`, is a no-op. */
	ensure(): void {
		if (this.requested) return;
		this.requested = true;
		this.fetchNow();
	}

	/**
	 * Load again, dropping whatever was in flight.
	 *
	 * Called on a debounced live event, and directly by the fork's own order pages: orders have
	 * no websocket channel of their own (see `$lib/api/live`'s `Resource` union), so placing or
	 * receiving one would otherwise leave the pill stale until some spool changed.
	 */
	refresh(): void {
		this.requested = true;
		this.controller?.abort();
		this.fetchNow();
	}

	/**
	 * Subscribe to the live channels that can change the count, returning the unsubscribe.
	 * Reference-counted: the two mounted badges share one pair of subscriptions, and the timer
	 * and the sockets go away only when the last of them is gone.
	 */
	start(): () => void {
		this.subscribers++;
		if (this.subscribers === 1) {
			const schedule = () => {
				if (this.timer) clearTimeout(this.timer);
				this.timer = setTimeout(() => {
					this.timer = null;
					this.refresh();
				}, REFRESH_DEBOUNCE_MS);
			};
			// A spool change moves a filament's remaining weight across its threshold; a filament
			// change can move the threshold itself (including from the page's own inline editor).
			// Vendors cannot affect the count -- the pill shows a number, not a name -- so unlike
			// the pages this does not open a third socket.
			this.offLive = [live.subscribe('spool', {}, schedule), live.subscribe('filament', {}, schedule)];
		}
		let stopped = false;
		return () => {
			if (stopped) return; // a component teardown must not decrement twice
			stopped = true;
			this.subscribers--;
			if (this.subscribers > 0) return;
			for (const off of this.offLive) off();
			this.offLive = [];
			if (this.timer) clearTimeout(this.timer);
			this.timer = null;
		};
	}

	private fetchNow(): void {
		const controller = new AbortController();
		this.controller = controller;
		void this.load(controller.signal);
	}

	private async load(signal: AbortSignal): Promise<void> {
		try {
			const [filaments, orders, fallbackG] = await Promise.all([
				listAllFilaments(signal),
				listOrders(signal),
				lowStockFallbackG(signal)
			]);
			this.count = badgeCount(filaments, fallbackG, orders);
		} catch (e) {
			// An abort is this store superseding itself, not a failure.
			if (isAbortError(e, signal)) return;
			// Leave the last known count standing: a pill that vanished on a transient network
			// blip would read as "nothing is low any more", which is the wrong thing to say.
			console.error('Failed to load the low stock badge count', e);
		} finally {
			// Only if nothing has superseded this load in the meantime.
			if (this.controller?.signal === signal) this.controller = null;
		}
	}
}

export const lowStockBadge = new LowStockBadge();
