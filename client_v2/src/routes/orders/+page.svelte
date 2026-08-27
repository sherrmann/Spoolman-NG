<script lang="ts">
	// Orders list page (#298; gate-feedback items #4/#5) — ported from
	// client/src/pages/orders/index.tsx: order #, shop, ordered date, a lines summary with arrived
	// counts, and the derived state pill. Every row opens the read/edit details modal
	// (OrderDetailsModal.svelte); the per-row "Arrived…" action opens the split-arrival dialog
	// (ArriveModal.svelte) directly, without going through the details modal. The "New order"
	// button opens the from-scratch builder (#324, NewOrderModal.svelte) — orders can also still be
	// born from the Low Stock flows (mark-as-ordered / bulk create).
	//
	// `?highlight=<orderId>` (written by OrderedPill.svelte's link, and previously by the Low Stock
	// and Home "Ordered" pills before this route existed) opens that order's details on load — the
	// one piece of this page's own contract that isn't a straight port, since upstream never had
	// anywhere for that link to land.
	//
	// Data loading/live-refresh follows routes/lowstock/+page.svelte's own pattern (an
	// AbortController-guarded load plus debounced live subscriptions) rather than a per-resource
	// cache, since this client has none for this fork's own aggregates. Orders have no live channel
	// of their own (see $lib/api/live's Resource union), so the dialogs below call refresh()
	// directly on success instead.
	import { page } from '$app/state';
	import { spoolSource } from '$lib/api/spoolSource';
	import { live } from '$lib/api/live';
	import { isAbortError } from '$lib/api/http';
	import { listAllFilaments, listOrders } from '$lib/ng/api';
	import { ng, plural } from '$lib/ng/i18n';
	import { summarizeLines } from '$lib/ng/ordersState';
	import { dateLocale } from '$lib/utils/datetime';
	import type { ForkFilament, Order } from '$lib/ng/types';
	import type { Vendor } from '$lib/types';
	import Button from '$components/Button.svelte';
	import OrderDetailsModal from '$lib/ng/components/OrderDetailsModal.svelte';
	import ArriveModal from '$lib/ng/components/ArriveModal.svelte';
	import NewOrderModal from '$lib/ng/components/NewOrderModal.svelte';

	// --- data loading ----------------------------------------------------------------

	let orders = $state<Order[]>([]);
	let filaments = $state<ForkFilament[]>([]);
	let vendors = $state<Vendor[]>([]);

	let loaded = $state(false);
	let loadError = $state(false);

	let controller = new AbortController();

	async function loadAll(signal: AbortSignal) {
		try {
			const [o, f, v] = await Promise.all([
				listOrders(signal),
				listAllFilaments(signal),
				spoolSource.listVendors(signal)
			]);
			orders = o;
			filaments = f;
			vendors = v;
			loadError = false;
		} catch (e) {
			if (isAbortError(e, signal)) return;
			console.error('Failed to load orders', e);
			loadError = true;
		} finally {
			loaded = true;
		}
	}

	function refresh() {
		controller.abort();
		controller = new AbortController();
		loadAll(controller.signal);
	}

	$effect(() => {
		refresh();
		// A spool/filament change doesn't change an order itself, but a filament rename or a
		// deletion changes what a line's name resolves to — cheaper to reload once, debounced,
		// than to teach this page's line-name lookup its own patch rule (same reasoning as
		// routes/lowstock/+page.svelte's scheduleRefresh).
		let timer: ReturnType<typeof setTimeout> | null = null;
		const scheduleRefresh = () => {
			if (timer) clearTimeout(timer);
			timer = setTimeout(() => {
				timer = null;
				refresh();
			}, 400);
		};
		const offFilament = live.subscribe('filament', {}, scheduleRefresh);
		const offVendor = live.subscribe('vendor', {}, scheduleRefresh);
		return () => {
			offFilament();
			offVendor();
			if (timer) clearTimeout(timer);
			controller.abort();
		};
	});

	// --- ?highlight=<orderId>: open that order's details once, on the first load that has it ------

	let highlightId = $state<number | undefined>(undefined);
	let highlightHandled = false;
	$effect(() => {
		if (!loaded || highlightHandled) return;
		highlightHandled = true;
		const raw = page.url.searchParams.get('highlight');
		if (!raw) return;
		const id = Number(raw);
		const match = orders.find((o) => o.id === id);
		if (match) {
			highlightId = id;
			detailsOrder = match;
		}
	});

	// --- dialogs ---------------------------------------------------------------------

	// The split-arrival dialog (US3), opened per-row from the "Arrived…" action below. The
	// read/edit details modal (gate-feedback item #5), opened by clicking anywhere on a row. The
	// from-scratch "New order" builder (#324), opened by the header button. All three are mounted
	// only while actually open, matching MarkOrderedDialog's own conditional-mount convention.
	let arrivingOrder = $state<Order | undefined>();
	let detailsOrder = $state<Order | undefined>();
	let creating = $state(false);

	function dialogSuccess() {
		arrivingOrder = undefined;
		detailsOrder = undefined;
		creating = false;
		refresh();
	}

	function orderedAtLabel(iso: string): string {
		const d = new Date(iso);
		if (Number.isNaN(d.getTime())) return '—';
		return new Intl.DateTimeFormat(dateLocale(), { month: 'short', day: 'numeric', year: 'numeric' }).format(
			d
		);
	}

	function orderLabel(order: Order): string {
		return order.orderNumber ?? `#${order.id}`;
	}
</script>

<svelte:head>
	<title>{ng.orders_title()} | Spoolman</title>
</svelte:head>

<div class="page scroll-y">
	<div class="header">
		<h1>{ng.orders_title()}</h1>
		<Button onclick={() => (creating = true)}>{ng.orders_new_order()}</Button>
	</div>

	{#if !loaded}
		<div class="state">{ng.loading()}</div>
	{:else if loadError}
		<div class="state error">
			<button class="retry" onclick={refresh}>{ng.buttons_refresh()}</button>
		</div>
	{:else if orders.length === 0}
		<p class="empty">{ng.orders_empty()}</p>
	{:else}
		<ul class="list">
			{#each orders as order (order.id)}
				{@const summary = summarizeLines(order)}
				<li
					class="row"
					class:arrived={order.state === 'arrived'}
					class:highlighted={order.id === highlightId}
				>
					<span class="row-left">
						<!-- The stretched-hit-target pattern from routes/lowstock/+page.svelte's `.name`,
						     with a <button> in place of an <a>: this opens a modal, not a navigation, so
						     there is no href for a real link to point at. Its ::after covers the whole row
						     (position:relative on .row) while the row's other controls are raised above it
						     with z-index, same as lowstock's `.row-right`. -->
						<button class="order-link" onclick={() => (detailsOrder = order)}>{orderLabel(order)}</button>
						<span class="meta">
							<span class="shop">{order.shop?.name ?? '—'}</span>
							<span class="dot" aria-hidden="true">·</span>
							<span class="ordered-at">{orderedAtLabel(order.orderedAt)}</span>
						</span>
					</span>
					<span class="lines-summary">
						{ng.orders_lines_summary({ arrived: summary.arrived, total: summary.total })}
						· {plural('orders_filaments_count', summary.filaments)}
					</span>
					<span class="row-right" onclick={(e) => e.stopPropagation()} role="none">
						<span class="state-pill" class:open={order.state === 'open'}>
							{order.state === 'open'
								? ng.orders_state_open({ count: summary.outstanding })
								: ng.orders_state_arrived()}
						</span>
						{#if order.state === 'open'}
							<Button variant="outline" onclick={() => (arrivingOrder = order)}>
								{ng.orders_arrived_action()}
							</Button>
						{/if}
					</span>
				</li>
			{/each}
		</ul>
	{/if}
</div>

{#if arrivingOrder}
	<ArriveModal
		order={arrivingOrder}
		{filaments}
		{vendors}
		onclose={() => (arrivingOrder = undefined)}
		onsuccess={dialogSuccess}
	/>
{/if}

{#if detailsOrder}
	<OrderDetailsModal
		order={detailsOrder}
		{filaments}
		{vendors}
		onclose={() => (detailsOrder = undefined)}
		onsuccess={dialogSuccess}
	/>
{/if}

{#if creating}
	<NewOrderModal {filaments} {vendors} onclose={() => (creating = false)} onsuccess={dialogSuccess} />
{/if}

<style>
	.page {
		max-width: 1100px;
		width: 100%;
		margin: 0 auto;
		padding: 20px 22px 40px;
		display: flex;
		flex-direction: column;
		gap: 24px;
	}

	.header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		flex-wrap: wrap;
	}
	.header h1 {
		margin: 0;
		font-size: 20px;
		font-weight: 800;
		letter-spacing: -0.02em;
	}

	.state {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 48px 0;
		color: var(--text-faint);
		font-size: 13px;
	}
	.retry {
		background: var(--accent-fill);
		color: #fff;
		border: none;
		border-radius: var(--radius);
		padding: 8px 16px;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}
	.retry:hover {
		background: var(--accent-fill-hover);
	}

	.empty {
		text-align: center;
		padding: 48px 0;
		color: var(--text-faint);
		font-size: 13px;
	}

	.list {
		display: flex;
		flex-direction: column;
		gap: 8px;
		/* These rows are a semantic list -- `getByRole("listitem")` is how the browser tests
		   address them -- but not a bulleted one. `display: flex` does NOT suppress an <li>'s
		   ::marker in Chromium, so without this every row rendered a disc, indented 40px by the
		   UA stylesheet's padding-inline-start. Measured via getComputedStyle, not guessed: the
		   markers sat in the list's padding against a matching background and were easy to miss
		   on every page but the narrow one. */
		list-style: none;
		margin: 0;
		padding: 0;
	}

	/* Arrived orders are done; grey them out so the eye goes to what's still open. */
	.row.arrived {
		opacity: 0.55;
	}
	/* Briefly calls out the order a `?highlight=` link pointed at (see the $effect above) — a
	   soft accent ring rather than a background fill, so it reads next to `.row.arrived`'s own
	   opacity change without the two visually fighting. */
	.row.highlighted {
		box-shadow: 0 0 0 2px var(--accent);
	}

	.row {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		width: 100%;
		padding: 14px 16px;
		border-radius: var(--radius-lg);
		background: var(--surface);
		border: 1px solid var(--border);
	}
	.row:hover {
		background: var(--surface-raised);
	}

	.row-left {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
		flex: 1;
	}
	.order-link {
		align-self: flex-start;
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		font-size: 13.5px;
		font-weight: 600;
		color: var(--text);
		cursor: pointer;
		text-align: left;
	}
	.order-link::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: inherit;
	}
	.order-link:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.meta {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		color: var(--text-faint);
		min-width: 0;
	}
	.shop {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.dot {
		flex: none;
	}
	.ordered-at {
		white-space: nowrap;
	}

	.lines-summary {
		flex: 1 1 auto;
		min-width: 0;
		font-size: 12.5px;
		color: var(--text-dim);
		text-align: center;
	}

	/* `.order-link` must NOT be positioned: its ::after is what stretches over the whole row,
	   and `position: relative` here would make the row's own box irrelevant and confine the
	   ::after to the button's text -- which is exactly the bug this replaces (a mid-row click
	   hit `.lines-summary` and did nothing). `.row` is the positioned ancestor; only the
	   controls that must sit ABOVE the stretched ::after are positioned and raised.
	   routes/lowstock/+page.svelte's `.name` / `.row-right` pair is the same arrangement. */
	.row-right {
		position: relative;
		z-index: 1;
		display: flex;
		align-items: center;
		gap: 12px;
		flex-shrink: 0;
	}

	/* Matches the React Tag colours this replaces: green while arrived, blue while open. */
	.state-pill {
		font-size: 11px;
		font-weight: 700;
		white-space: nowrap;
		padding: 3px 10px;
		border-radius: 999px;
		background: color-mix(in srgb, var(--success) 15%, transparent);
		color: var(--success);
	}
	.state-pill.open {
		background: var(--accent-wash);
		color: var(--accent-soft);
	}

	@media (max-width: 780px) {
		.row {
			flex-wrap: wrap;
		}
		.lines-summary {
			text-align: left;
			flex-basis: 100%;
			order: 3;
		}
		.row-right {
			margin-left: auto;
		}
	}
</style>
