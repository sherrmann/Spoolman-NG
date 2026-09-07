<script lang="ts">
	// The red count on the "Low Stock" nav tab (#417). Everything it knows lives in the shared
	// store beside it, so the two mounted copies of NavTabs (desktop and mobile, see TopBar)
	// show the same number from one load.
	import { lowStockBadge } from '$lib/ng/lowStockBadge.svelte';

	$effect(() => {
		lowStockBadge.ensure();
		// The store reference-counts its live subscriptions, so returning this is enough: the
		// sockets go away only when the last badge is unmounted.
		return lowStockBadge.start();
	});
</script>

<!-- A <span>, never a button: this sits inside the tab's own <a>, where interactive content is
     invalid, and the number belongs to that link. It carries no aria-label on purpose -- the
     link then announces as "Low Stock 3", which is exactly what it means, where a label would
     either repeat the tab's name or hide the count from the accessibility tree entirely. -->
{#if lowStockBadge.count > 0}
	<span class="badge">{lowStockBadge.count}</span>
{/if}

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		/* Wide enough that a single digit reads as a circle rather than a slot. */
		min-width: 17px;
		height: 17px;
		margin-left: 6px;
		padding: 0 5px;
		border-radius: 999px;
		background: var(--danger);
		color: #fff;
		font-size: 10.5px;
		font-weight: 700;
		line-height: 1;
		box-sizing: border-box;
	}
</style>
