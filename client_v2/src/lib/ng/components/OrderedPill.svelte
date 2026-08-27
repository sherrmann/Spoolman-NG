<script lang="ts">
	// Calm on-order pill for a Low Stock row already covered by an open order — ported from
	// client/src/pages/orders/orderPill.tsx. Upstream links through to an /orders page and
	// shows a shop name; this client has neither yet (no /orders route, and this fork's
	// `Order` type carries no shop reference -- see the doc comment on
	// `openOrdersByFilament` in $lib/ng/analytics), so the pill renders as plain text, same
	// as the identical pill already on the dashboard's Low Stock tab
	// (routes/home/+page.svelte's `lowStockRow` snippet).
	import type { OnOrderInfo } from '$lib/ng/analytics';

	let { onOrder }: { onOrder: OnOrderInfo } = $props();

	/** "today" same-day, else "<n>d". */
	function age(orderedAt: string, now: Date = new Date()): string {
		const days = Math.floor((now.getTime() - new Date(orderedAt).getTime()) / 86_400_000);
		return days <= 0 ? 'today' : `${days}d`;
	}
</script>

<span class="pill">Ordered · {age(onOrder.orderedAt)}</span>

<style>
	.pill {
		font-size: 11px;
		font-weight: 600;
		padding: 3px 9px;
		border-radius: 999px;
		background: var(--accent-wash);
		color: var(--accent-soft);
		white-space: nowrap;
	}
</style>
