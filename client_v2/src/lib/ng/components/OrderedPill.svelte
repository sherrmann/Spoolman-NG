<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   The href below is built from resolve('/orders') plus a query string; resolving it a
	   second time would double-apply the deploy base path. See routes/lowstock/+page.svelte
	   for the same pattern. */
	// Calm on-order pill for a Low Stock row already covered by an open order — ported from
	// client/src/pages/orders/orderPill.tsx. Now that /orders exists, this links straight to
	// the order (opening it via `?highlight=<id>`, which routes/orders/+page.svelte reads on
	// load) and shows the shop name when the caller has one to hand it — same as upstream's
	// `formatOrderedPill`/`OrderedPill`. `shopName` is optional because not every caller has
	// it joined onto its on-order lookup yet (routes/home and routes/lowstock's Low Stock
	// rows currently pass none, same as before this pill grew a shop).
	import { resolve } from '$app/paths';
	import { formatOrderedPill } from '$lib/ng/ordersState';
	import type { OnOrderInfo } from '$lib/ng/analytics';

	let { onOrder, shopName }: { onOrder: OnOrderInfo; shopName?: string } = $props();

	let href = $derived(`${resolve('/orders')}?highlight=${onOrder.orderId}`);
</script>

<a class="pill" {href}>{formatOrderedPill(onOrder, shopName)}</a>

<style>
	.pill {
		display: inline-block;
		font-size: 11px;
		font-weight: 600;
		padding: 3px 9px;
		border-radius: 999px;
		background: var(--accent-wash);
		color: var(--accent-soft);
		white-space: nowrap;
		text-decoration: none;
	}
	.pill:hover {
		background: var(--accent-wash-soft);
	}
</style>
