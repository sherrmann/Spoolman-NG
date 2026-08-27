<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   Every href/goto target below goes through libraryHref() from $lib/library/params,
	   which already resolves against the deploy base path; resolving again would double-
	   apply it. See routes/home/+page.svelte for the same pattern. */
	// Low Stock full page (#298 redesign) — ported from client/src/pages/lowstock/index.tsx:
	// the same merged per-filament list as the dashboard's Low Stock tab
	// (routes/home/+page.svelte), in a larger full-page layout with sections, inline
	// threshold edit, and the Ordered pill. Also hosts the US1 "Mark as ordered" per-row
	// action and the US2 multi-select "Create order" button.
	//
	// Data loading/live-refresh follows routes/home/+page.svelte's own pattern (an
	// AbortController-guarded load plus debounced live subscriptions) rather than a
	// per-resource cache, since this client has none for this fork's own aggregates.
	import { spoolSource } from '$lib/api/spoolSource';
	import { live } from '$lib/api/live';
	import { isAbortError } from '$lib/api/http';
	import { listAllFilaments, listOrders, lowStockFallbackG } from '$lib/ng/api';
	import { ng } from '$lib/ng/i18n';
	import {
		computeLowStock,
		getFilamentName,
		openOrdersByFilament,
		type LowStockRow
	} from '$lib/ng/analytics';
	import type { ForkFilament, Order } from '$lib/ng/types';
	import type { Vendor } from '$lib/types';
	import { weightAuto } from '$lib/utils/format';
	import { libraryHref } from '$lib/library/params';
	import Swatch from '$components/Swatch.svelte';
	import Button from '$components/Button.svelte';
	import ThresholdEdit from '$lib/ng/components/ThresholdEdit.svelte';
	import OrderedPill from '$lib/ng/components/OrderedPill.svelte';
	import MarkOrderedDialog from '$lib/ng/components/MarkOrderedDialog.svelte';
	import CreateOrderModal from '$lib/ng/components/CreateOrderModal.svelte';

	// --- data loading ----------------------------------------------------------------

	let filaments = $state<ForkFilament[]>([]);
	let vendors = $state<Vendor[]>([]);
	let orders = $state<Order[]>([]);
	let fallbackG = $state(0);

	let loaded = $state(false);
	let loadError = $state(false);

	let controller = new AbortController();

	async function loadAll(signal: AbortSignal) {
		try {
			const [f, v, o, g] = await Promise.all([
				listAllFilaments(signal),
				spoolSource.listVendors(signal),
				listOrders(signal),
				lowStockFallbackG(signal)
			]);
			filaments = f;
			vendors = v;
			orders = o;
			fallbackG = g;
			loadError = false;
		} catch (e) {
			if (isAbortError(e, signal)) return;
			console.error('Failed to load low stock data', e);
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
		// A spool/filament change can move a filament in or out of low stock, or change its
		// remaining weight; a vendor rename changes the displayed name -- cheaper to reload
		// everything once, debounced, than to teach each row its own patch rule (same
		// reasoning as routes/home/+page.svelte's scheduleRefresh). Orders have no live
		// channel of their own (see $lib/api/live's Resource union), so the mark-ordered and
		// bulk-create flows below call refresh() directly on success instead.
		let timer: ReturnType<typeof setTimeout> | null = null;
		const scheduleRefresh = () => {
			if (timer) clearTimeout(timer);
			timer = setTimeout(() => {
				timer = null;
				refresh();
			}, 400);
		};
		const offSpool = live.subscribe('spool', {}, scheduleRefresh);
		const offFilament = live.subscribe('filament', {}, scheduleRefresh);
		const offVendor = live.subscribe('vendor', {}, scheduleRefresh);
		return () => {
			offSpool();
			offFilament();
			offVendor();
			if (timer) clearTimeout(timer);
			controller.abort();
		};
	});

	// --- analytics (pure logic lives in $lib/ng/analytics, unit-tested there) --------

	let orderMap = $derived(openOrdersByFilament(orders));
	let lowStock = $derived(computeLowStock(filaments, fallbackG, orderMap));

	// US1: the single-filament dialog. US2: the bulk multi-select selection set + its
	// modal. Both are mounted only while actually open, so their shop lookups don't run
	// on a plain read of this page (see MarkOrderedDialog's own doc comment).
	let markOrderedFilament = $state<ForkFilament | undefined>();
	let selected = $state<Set<string>>(new Set());
	let bulkOpen = $state(false);

	function toggleSelect(filamentId: string) {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- transient local; `selected` updates via reassignment below
		const next = new Set(selected);
		if (next.has(filamentId)) next.delete(filamentId);
		else next.add(filamentId);
		selected = next;
	}

	// A row already on order can't be (re)selected -- this also drops any id that was
	// selected and then moved on-order elsewhere (e.g. another tab's per-row action).
	let selectableRows = $derived([...lowStock.explicit, ...lowStock.fallback].filter((r) => !r.onOrder));
	let selectedRows = $derived(selectableRows.filter((r) => selected.has(r.filament.id)));

	function markOrderedSuccess() {
		markOrderedFilament = undefined;
		refresh();
	}
	function bulkSuccess() {
		bulkOpen = false;
		selected = new Set();
		refresh();
	}

	// A plain href rather than a click handler: the row's name is a real link (stretched over the
	// row in CSS), so the browser supplies keyboard activation, middle-click and open-in-new-tab
	// for free instead of this file reimplementing them.
	const filamentHref = (id: string) => libraryHref('filament', id);
</script>

<svelte:head>
	<title>{ng.low_stock_title()} | Spoolman</title>
</svelte:head>

<div class="page scroll-y">
	<div class="header">
		<h1>{ng.low_stock_title()}</h1>
		<div class="header-actions">
			{#if selectedRows.length > 0}
				<span class="selected-count">{ng.orders_selected_count({ count: selectedRows.length })}</span>
			{/if}
			<Button variant="outline" disabled={selectedRows.length === 0} onclick={() => (bulkOpen = true)}>
				{ng.orders_create_order()}
			</Button>
		</div>
	</div>

	{#if !loaded}
		<div class="state">{ng.loading()}</div>
	{:else if loadError}
		<div class="state error">
			<button class="retry" onclick={refresh}>{ng.buttons_refresh()}</button>
		</div>
	{:else if lowStock.count === 0}
		<p class="empty">{ng.low_stock_empty()}</p>
	{:else}
		<div class="sections">
			{@render section(lowStock.explicit, ng.low_stock_section_explicit())}
			{@render section(lowStock.fallback, ng.low_stock_section_fallback({ grams: fallbackG }))}
		</div>
	{/if}
</div>

{#snippet section(rows: LowStockRow[], subhead: string)}
	{#if rows.length > 0}
		<div class="section">
			<div class="subhead">{subhead}</div>
			<!-- Labels the weight column below now that the threshold moved onto its own
			     "Adjust threshold" button, mirroring the row's right-side columns so it lines
			     up above the actual weight (ported from lowstock.css's equivalent header). -->
			<div class="columns-header">
				<span class="ch-action"></span>
				<span class="ch-weight">{ng.low_stock_remaining_header()}</span>
				<span class="ch-threshold"></span>
			</div>
			<ul class="list">
				{#each rows as row (row.filament.id)}
					{@render rowItem(row)}
				{/each}
			</ul>
		</div>
	{/if}
{/snippet}

{#snippet rowItem(row: LowStockRow)}
	<!-- A real <a> can't be used here: the row holds real interactive children (the
	     checkbox, the mark-ordered/threshold buttons) and nesting those inside an <a>
	     is invalid HTML. A keyboard-operable div matches upstream's clickable Card
	     (client/src/pages/lowstock/index.tsx) while staying valid and reachable by
	     keyboard, which the antd Card it replaces was not. -->
	<li class="row">
		<span class="row-left">
			<!-- Slot always renders (even empty) so the swatch/name that follows lines up the
			     same whether or not a checkbox is present -- an already-ordered row can't be
			     added to another order, so it has none. -->
			<span class="checkbox-slot">
				{#if !row.onOrder}
					<input
						type="checkbox"
						checked={selected.has(row.filament.id)}
						aria-label={getFilamentName(row.filament, vendors)}
						onclick={(e) => e.stopPropagation()}
						onchange={() => toggleSelect(row.filament.id)}
					/>
				{/if}
			</span>
			<Swatch
				colors={row.filament.colors}
				direction={row.filament.multiColorDirection}
				size={42}
				radius={8}
			/>
			<span class="info">
				<a class="name" href={filamentHref(row.filament.id)}>{getFilamentName(row.filament, vendors)}</a>
				<span class="material">{row.filament.material || '?'}</span>
			</span>
		</span>
		<span class="row-right" onclick={(e) => e.stopPropagation()} role="none">
			<span class="action-col">
				{#if row.onOrder}
					<OrderedPill onOrder={row.onOrder} />
				{:else}
					<Button variant="outline" onclick={() => (markOrderedFilament = row.filament)}>
						{ng.orders_mark_ordered()}
					</Button>
				{/if}
			</span>
			<!-- Remaining weight only -- the threshold lives on the "Adjust threshold" button
			     instead. Red while actionable, muted once on order. -->
			<span class="weight" class:actionable={!row.onOrder} class:on-order={!!row.onOrder}>
				{ng.low_stock_remaining_left({ amount: weightAuto(row.remaining) })}
			</span>
			<span class="threshold-col">
				<ThresholdEdit
					filamentId={row.filament.id}
					value={row.filament.lowStockThreshold}
					onSaved={refresh}
				/>
			</span>
		</span>
	</li>
{/snippet}

{#if markOrderedFilament}
	<MarkOrderedDialog
		filament={markOrderedFilament}
		{vendors}
		onclose={() => (markOrderedFilament = undefined)}
		onsuccess={markOrderedSuccess}
	/>
{/if}

{#if bulkOpen}
	<CreateOrderModal
		rows={selectedRows}
		{vendors}
		onclose={() => (bulkOpen = false)}
		onsuccess={bulkSuccess}
	/>
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
	.header-actions {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.selected-count {
		font-size: 12.5px;
		color: var(--text-dim);
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

	.sections {
		display: flex;
		flex-direction: column;
		gap: 24px;
	}
	.subhead {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--text-faint);
		margin-bottom: 12px;
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

	/* The row is a container, not a control. Its filament name is a real link stretched over
	   the whole row by ::after, so the entire row is clickable while staying a link: middle-click
	   and open-in-new-tab keep working, and a screen reader announces a link rather than a
	   button that happens to navigate. The alternative -- making the row itself interactive --
	   cannot be an <a>, because the row holds a checkbox and two buttons and an <a> may not
	   contain interactive content. The controls sit above the stretched layer via z-index. */
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
		cursor: pointer;
		text-align: left;
		font: inherit;
		color: inherit;
	}
	.row:hover {
		background: var(--surface-raised);
	}
	.row:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.row-left {
		display: flex;
		align-items: center;
		gap: 16px;
		min-width: 0;
		flex: 1;
	}
	/* Reserves the checkbox's width whether or not one actually renders, so the
	   swatch/name that follows always lands at the same x position across every row. */
	.checkbox-slot {
		width: 16px;
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.checkbox-slot input {
		accent-color: var(--accent);
	}
	.info {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.name {
		font-size: 13.5px;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.material {
		font-size: 12px;
		color: var(--text-faint);
		margin-top: 2px;
	}

	.name::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: inherit;
	}
	.checkbox-slot,
	.row-right {
		position: relative;
		z-index: 1;
	}
	.row-right {
		display: flex;
		align-items: center;
		gap: 16px;
		flex-shrink: 0;
		text-align: right;
	}
	/* The action (Mark as ordered / Ordered pill) and threshold-button columns share a
	   min-width so the "Remaining" column header above lines up over the actual weight
	   regardless of which variant renders in the neighbouring columns. */
	.action-col,
	.threshold-col {
		min-width: 140px;
		display: flex;
		justify-content: flex-end;
	}
	.weight {
		font-size: 14px;
		font-weight: 700;
		white-space: nowrap;
		min-width: 64px;
		text-align: right;
	}
	.weight.actionable {
		color: var(--danger-soft);
	}
	.weight.on-order {
		color: var(--text-faint);
	}

	.columns-header {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 16px;
		margin: 0 0 8px;
		padding-right: 16px;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-faint);
	}
	.ch-action,
	.ch-threshold {
		min-width: 140px;
	}
	.ch-weight {
		min-width: 64px;
		text-align: right;
	}

	@media (max-width: 700px) {
		.row {
			flex-wrap: wrap;
		}
		.row-right {
			flex-wrap: wrap;
			justify-content: flex-start;
			width: 100%;
			margin-left: 32px;
		}
		.columns-header {
			display: none;
		}
	}
</style>
