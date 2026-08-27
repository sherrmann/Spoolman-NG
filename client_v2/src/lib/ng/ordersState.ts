/**
 * Pure order-state presentation helpers: the Orders-list line summary, and the "Ordered" pill
 * text shown on a Low Stock row that already has an open order.
 *
 * Framework-free, like orderBody.ts, so the counts/text can be checked against hand-computed
 * values without mounting a component. formatOrderedPill is ported from the React client's
 * orderPill.tsx, but has no Svelte component of its own to be extracted *from* here (unlike
 * arriveBody.ts) — it's colocated with summarizeLines rather than given its own file because it
 * shares the `OnOrderInfo` shape with analytics.ts's low-stock rows, which is exactly what
 * summarizeLines' output (via the Orders-list state pill) also describes: an order's line state.
 */
import type { OnOrderInfo } from './analytics';
import type { Order } from './types';

export interface LinesSummary {
	total: number;
	arrived: number;
	outstanding: number;
	filaments: number;
}

/** Roll an order's lines into counts for the Orders-list summary column. */
export function summarizeLines(order: Order): LinesSummary {
	let total = 0;
	let arrived = 0;
	// Distinct filaments, not line count -- a split line (same filament, e.g. partial arrival
	// across two lines) must not double-count. Filament ids are strings in this client (unlike the
	// React source's numeric ones -- see orderBody.ts), so the set is keyed by string.
	const filamentIds = new Set<string>();
	for (const l of order.lines) {
		total += l.quantity;
		if (l.arrivedAt) arrived += l.quantity;
		filamentIds.add(l.filamentId);
	}
	return { total, arrived, outstanding: total - arrived, filaments: filamentIds.size };
}

/** Compose the calm on-order pill text: "Ordered · <age> · <shop>" ("today" same-day; shop omitted when unknown). */
export function formatOrderedPill(
	onOrder: OnOrderInfo,
	shopName: string | undefined,
	now: Date = new Date()
): string {
	const days = Math.floor((now.getTime() - new Date(onOrder.orderedAt).getTime()) / 86_400_000);
	const age = days <= 0 ? 'today' : `${days}d`;
	return shopName ? `Ordered · ${age} · ${shopName}` : `Ordered · ${age}`;
}
