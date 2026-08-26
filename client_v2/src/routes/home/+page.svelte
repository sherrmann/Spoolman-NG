<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   Every href below is either libraryHref()/resolve() from $lib/library/params (already
	   base-path aware) or a local constant built the same way; resolving again would double-
	   apply the base path. See routes/dashboard/+page.svelte for the same pattern. */
	import { resolve } from '$app/paths';
	import { libraryHref } from '$lib/library/params';
	import { live } from '$lib/api/live';
	import { isAbortError } from '$lib/api/http';
	import { spoolSource } from '$lib/api/spoolSource';
	import { listAllSpools, listAllFilaments, listOrders, lowStockFallbackG } from '$lib/ng/api';
	import { ng, plural } from '$lib/ng/i18n';
	import * as m from '$lib/paraglide/messages';
	import {
		computeLowStock,
		distinctMaterialCount,
		getFilamentName,
		getSpoolName,
		locationBreakdown,
		materialBreakdown,
		openOrdersByFilament,
		recentSpools,
		registeredWithinDays,
		STALE_ALERT_DAYS,
		STALE_WARN_DAYS,
		staleSpools,
		totalRemainingWeight,
		totalValue,
		vendorBreakdown,
		type LowStockRow
	} from '$lib/ng/analytics';
	import type { ForkFilament, Order } from '$lib/ng/types';
	import type { Spool, Vendor } from '$lib/types';
	import { settings } from '$lib/stores/settings.svelte';
	import { ui } from '$lib/stores/ui.svelte';
	import { formatDurationShort } from '$lib/utils/datetime';
	import { weightAuto } from '$lib/utils/format';
	import { truncTitle } from '$lib/actions/truncated';
	import Swatch from '$components/Swatch.svelte';
	import BreakdownBar from '$lib/ng/components/BreakdownBar.svelte';
	import Timeline from '$lib/ng/components/Timeline.svelte';
	import UsageChart from '$lib/ng/components/UsageChart.svelte';
	import Database from '@lucide/svelte/icons/database';
	import Highlighter from '@lucide/svelte/icons/highlighter';
	import Store from '@lucide/svelte/icons/store';
	import ShoppingBag from '@lucide/svelte/icons/shopping-bag';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import LayoutGrid from '@lucide/svelte/icons/layout-grid';
	import FlaskConical from '@lucide/svelte/icons/flask-conical';
	import ChartArea from '@lucide/svelte/icons/chart-area';
	import MapPin from '@lucide/svelte/icons/map-pin';

	// Ported from client/src/pages/home/index.tsx. That page reads straight off refine's
	// per-resource `useList` cache; this client has no such cache for the fork's own
	// aggregates, so the four lists below are fetched directly (see $lib/ng/api) and kept
	// live the same way routes/dashboard/+page.svelte does — a spool/filament/vendor event
	// schedules one debounced reload rather than patching each derived view by hand, which
	// would mean teaching every KPI/breakdown/timeline below its own patch rule.

	// --- data loading --------------------------------------------------------

	let spools = $state<Spool[]>([]);
	let filaments = $state<ForkFilament[]>([]);
	let vendors = $state<Vendor[]>([]);
	let orders = $state<Order[]>([]);
	let fallbackG = $state(0);

	let loaded = $state(false);
	let loadError = $state(false);

	let controller = new AbortController();

	async function loadAll(signal: AbortSignal) {
		try {
			const [s, f, v, o, g] = await Promise.all([
				listAllSpools(signal),
				listAllFilaments(signal),
				spoolSource.listVendors(signal),
				listOrders(signal),
				lowStockFallbackG(signal)
			]);
			spools = s;
			filaments = f;
			vendors = v;
			orders = o;
			fallbackG = g;
			loadError = false;
		} catch (e) {
			if (isAbortError(e, signal)) return;
			console.error('Failed to load dashboard data', e);
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
		// A live change to any of the three resources can move a spool between groups,
		// change a filament's low-stock standing, or rename a vendor — cheaper to reload
		// everything once, debounced, than to teach each KPI/breakdown/timeline below its
		// own patch rule (see routes/dashboard/+page.svelte's scheduleCountRefresh).
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

	let hasSpools = $derived(spools.length > 0);

	// --- analytics (pure logic lives in $lib/ng/analytics, unit-tested there) ----------

	let filamentById = $derived(new Map(filaments.map((f) => [f.id, f])));
	let orderMap = $derived(openOrdersByFilament(orders));
	let lowStock = $derived(computeLowStock(filaments, fallbackG, orderMap));
	let hasLowStock = $derived(lowStock.count > 0);
	let totalRemaining = $derived(totalRemainingWeight(spools));
	let totalVal = $derived(totalValue(spools, filaments));
	let distinctMaterials = $derived(distinctMaterialCount(filaments));
	let registeredThisMonth = $derived(registeredWithinDays(spools, 30));
	let materialData = $derived(materialBreakdown(spools, filaments));
	let vendorData = $derived(vendorBreakdown(spools, filaments, vendors));
	let locationData = $derived(locationBreakdown(spools, ng.locations_no_location()));
	let topVendorName = $derived(vendorData[0]?.[0] ?? '-');
	let weightParts = $derived(weightAuto(totalRemaining).split(' '));

	function spoolDetail(spool: Spool): string {
		const material = filamentById.get(spool.filamentId)?.material ?? '';
		return `${material} · ${weightAuto(spool.remaining)} · ${spool.location || ng.locations_no_location()}`;
	}

	function daysSince(iso: string): number {
		return (Date.now() - new Date(iso).getTime()) / 86_400_000;
	}

	let recentEntries = $derived(
		recentSpools(spools).map((spool, idx) => ({
			id: spool.id,
			href: libraryHref('spool', String(spool.id)),
			name: getSpoolName(spool, filaments, vendors),
			detail: spoolDetail(spool),
			timeLabel: m['library.dateFilter.ago']({ span: formatDurationShort(spool.lastUsed) }),
			active: idx === 0,
			color: idx === 0 ? 'var(--accent)' : undefined
		}))
	);

	let staleEntries = $derived(
		staleSpools(spools).map(({ spool, staleSince, neverUsed }) => {
			const days = daysSince(staleSince);
			const color =
				days >= STALE_ALERT_DAYS
					? 'var(--danger-soft)'
					: days >= STALE_WARN_DAYS
						? 'var(--unused-text)'
						: undefined;
			const ago = m['library.dateFilter.ago']({ span: formatDurationShort(staleSince) });
			return {
				id: spool.id,
				href: libraryHref('spool', String(spool.id)),
				name: getSpoolName(spool, filaments, vendors),
				detail: spoolDetail(spool),
				timeLabel: neverUsed ? `${ng.home_never_used()} · ${ago}` : ago,
				color
			};
		})
	);

	/** Rank tier for a breakdown/location row: 0 highlights the top row, 1 the next couple. */
	function tier(idx: number): 0 | 1 | 2 {
		return idx === 0 ? 0 : idx < 3 ? 1 : 2;
	}

	// Upstream's on-order pill (orders/orderPill.tsx) is plain "Ordered · <age>" with no
	// i18n of its own; this fork's Order carries no shop reference to add back in, so the
	// port keeps it exactly that literal rather than inventing a locale id for one word.
	function orderedAge(orderedAt: string, now: Date = new Date()): string {
		const days = Math.floor((now.getTime() - new Date(orderedAt).getTime()) / 86_400_000);
		return days <= 0 ? 'today' : `${days}d`;
	}

	// This client has no /spool or /filament listing route (client/src/pages/home's KPI
	// links) — the Library at "/" is both, told apart by group mode — and no /locations
	// page, whose nearest equivalent here is the dashboard board grouped by location.
	const spoolListHref = `${resolve('/')}?group=none`;
	const filamentListHref = resolve('/'); // default view already groups by filament
	const vendorListHref = `${resolve('/')}?group=vendor`;
	const locationBoardHref = `${resolve('/dashboard')}?by=location`;

	// home.description names a <helpPageLink> this client doesn't have a route for yet;
	// render its text without a dead link rather than dropping the sentence.
	let description = $derived.by(() => {
		const raw = ng.home_description();
		const open = raw.indexOf('<helpPageLink>');
		const close = raw.indexOf('</helpPageLink>');
		if (open === -1 || close === -1) return { before: raw, link: '', after: '' };
		return {
			before: raw.slice(0, open),
			link: raw.slice(open + '<helpPageLink>'.length, close),
			after: raw.slice(close + '</helpPageLink>'.length)
		};
	});

	// --- tabs ------------------------------------------------------------------------

	type TabKey = 'lowstock' | 'swatches' | 'materials' | 'vendors' | 'usage';
	let activeTab = $state<TabKey | null>(null);

	// Chooses the opening tab once, the first time data is in hand — same "uncontrolled
	// default" as upstream's antd Tabs `defaultActiveKey`, so a live update that later
	// clears the low-stock count doesn't rip the tab out from under whoever is reading it.
	$effect(() => {
		if (activeTab === null && loaded && !loadError) activeTab = hasLowStock ? 'lowstock' : 'materials';
	});
</script>

<svelte:head>
	<!-- Composed rather than taken from a documentTitle id: upstream keeps one id per route
	     holding the whole "Name | Spoolman" string, and those are untranslated in most locales.
	     Building it from the page name localizes the half that varies. -->
	<title>{ng.home_home()} | Spoolman</title>
</svelte:head>

<div class="page">
	{#if !loaded}
		<div class="state">{ng.loading()}</div>
	{:else if loadError}
		<div class="state error">
			<h2>{ng.home_load_error_title()}</h2>
			<p>{ng.home_load_error_desc()}</p>
			<button class="retry" onclick={refresh}>{ng.buttons_refresh()}</button>
		</div>
	{:else if !hasSpools}
		<div class="empty-hero">
			<div class="empty-hero-icon"><Database size={40} /></div>
			<h2>{ng.home_welcome()}</h2>
			<p>{description.before}<strong>{description.link}</strong>{description.after}</p>
			<button class="empty-hero-btn" onclick={() => ui.openAddModal()}>{ng.spool_titles_create()}</button>
		</div>
	{:else}
		<div class="kpi-grid">
			<a class="kpi-card" href={spoolListHref}>
				<Database class="kpi-bg-icon" />
				<div class="kpi-label">{ng.spool_spool()}</div>
				<div class="kpi-value">{spools.length}</div>
				<div class="kpi-footer" style="color:var(--success)">
					+{registeredThisMonth}
					{ng.home_kpi_this_month()}
				</div>
			</a>

			<a class="kpi-card" href={filamentListHref}>
				<Highlighter class="kpi-bg-icon" />
				<div class="kpi-label">{ng.filament_filament()}</div>
				<div class="kpi-value">{filaments.length}</div>
				<div class="kpi-footer" style="color:var(--accent-soft)">
					{plural('home_kpi_materials', distinctMaterials)}
				</div>
			</a>

			<a class="kpi-card" href={vendorListHref}>
				<Store class="kpi-bg-icon" />
				<div class="kpi-label">{ng.vendor_vendor()}</div>
				<div class="kpi-value">{vendors.length}</div>
				<div class="kpi-footer muted">{ng.home_kpi_top()}: {topVendorName}</div>
			</a>

			<a class="kpi-card" href={spoolListHref}>
				<ShoppingBag class="kpi-bg-icon" />
				<div class="kpi-label">{ng.home_total_weight()}</div>
				<div class="kpi-value">{weightParts[0]} <span class="kpi-unit">{weightParts[1]}</span></div>
				{#if lowStock.count > 0}
					<div class="kpi-footer danger">
						<TriangleAlert size={11} />
						{lowStock.count}
						{ng.home_low_stock().toUpperCase()}
					</div>
				{:else}
					<div class="kpi-footer muted">
						{ng.home_total_value()}: {settings.formatPrice(totalVal)}
					</div>
				{/if}
			</a>
		</div>

		<div class="main">
			<div class="left">
				<div class="tabbar" role="tablist">
					<button
						type="button"
						role="tab"
						id="tab-lowstock"
						aria-selected={activeTab === 'lowstock'}
						aria-controls="panel-lowstock"
						class="tab-btn"
						class:active={activeTab === 'lowstock'}
						onclick={() => (activeTab = 'lowstock')}
					>
						{#if hasLowStock}<TriangleAlert size={13} class="danger" />{/if}
						{ng.home_low_stock()}
					</button>
					<button
						type="button"
						role="tab"
						id="tab-swatches"
						aria-selected={activeTab === 'swatches'}
						aria-controls="panel-swatches"
						class="tab-btn"
						class:active={activeTab === 'swatches'}
						onclick={() => (activeTab = 'swatches')}
					>
						<LayoutGrid size={13} />
						{ng.home_all_spools()}
					</button>
					<button
						type="button"
						role="tab"
						id="tab-materials"
						aria-selected={activeTab === 'materials'}
						aria-controls="panel-materials"
						class="tab-btn"
						class:active={activeTab === 'materials'}
						onclick={() => (activeTab = 'materials')}
					>
						<FlaskConical size={13} />
						{ng.home_by_material()}
					</button>
					<button
						type="button"
						role="tab"
						id="tab-vendors"
						aria-selected={activeTab === 'vendors'}
						aria-controls="panel-vendors"
						class="tab-btn"
						class:active={activeTab === 'vendors'}
						onclick={() => (activeTab = 'vendors')}
					>
						<Store size={13} />
						{ng.home_by_vendor()}
					</button>
					<button
						type="button"
						role="tab"
						id="tab-usage"
						aria-selected={activeTab === 'usage'}
						aria-controls="panel-usage"
						class="tab-btn"
						class:active={activeTab === 'usage'}
						onclick={() => (activeTab = 'usage')}
					>
						<ChartArea size={13} />
						{ng.home_usage_tab()}
					</button>
				</div>

				<div class="panel-wrap">
					{#if activeTab === 'lowstock'}
						<div role="tabpanel" id="panel-lowstock" aria-labelledby="tab-lowstock" class="panel">
							{#if lowStock.count === 0}
								<p class="empty">{ng.home_all_stocked()}</p>
							{:else}
								{#if lowStock.explicit.length > 0}
									<div class="subhead">{ng.low_stock_section_explicit()}</div>
									<div class="lowstock-list">
										{#each lowStock.explicit as row (row.filament.id)}
											{@render lowStockRow(row)}
										{/each}
									</div>
								{/if}
								{#if lowStock.fallback.length > 0}
									<div class="subhead">{ng.low_stock_section_fallback({ grams: fallbackG })}</div>
									<div class="lowstock-list">
										{#each lowStock.fallback as row (row.filament.id)}
											{@render lowStockRow(row)}
										{/each}
									</div>
								{/if}
							{/if}
						</div>
					{:else if activeTab === 'swatches'}
						<div role="tabpanel" id="panel-swatches" aria-labelledby="tab-swatches" class="panel">
							{#if spools.length === 0}
								<p class="empty">{ng.home_no_spools()}</p>
							{:else}
								<div class="swatch-grid">
									{#each spools as spool (spool.id)}
										{@const filament = filamentById.get(spool.filamentId)}
										<a
											class="swatch-item"
											href={libraryHref('spool', String(spool.id))}
											title={getSpoolName(spool, filaments, vendors)}
										>
											<Swatch
												colors={filament?.colors}
												direction={filament?.multiColorDirection}
												size={30}
												radius={6}
											/>
										</a>
									{/each}
								</div>
							{/if}
						</div>
					{:else if activeTab === 'materials'}
						<div role="tabpanel" id="panel-materials" aria-labelledby="tab-materials" class="panel">
							<div class="bar-list">
								{#each materialData as [material, stat], i (material)}
									<BreakdownBar
										label={material}
										value={weightAuto(stat.weight)}
										pct={(stat.weight / (materialData[0]?.[1].weight || 1)) * 100}
										tier={tier(i)}
									/>
								{/each}
							</div>
						</div>
					{:else if activeTab === 'vendors'}
						<div role="tabpanel" id="panel-vendors" aria-labelledby="tab-vendors" class="panel">
							<div class="bar-list">
								{#each vendorData as [vendor, count], i (vendor)}
									<BreakdownBar
										label={vendor}
										value={`${count} ${ng.spool_spool()}`}
										pct={(count / (vendorData[0]?.[1] || 1)) * 100}
										tier={tier(i)}
									/>
								{/each}
							</div>
						</div>
					{:else if activeTab === 'usage'}
						<div role="tabpanel" id="panel-usage" aria-labelledby="tab-usage" class="panel">
							<UsageChart />
						</div>
					{/if}
				</div>
			</div>

			<div class="right">
				<div class="right-section">
					<h3 class="section-title">{ng.home_recently_used()}</h3>
					{#if recentEntries.length === 0}
						<p class="empty">{ng.home_no_recent()}</p>
					{:else}
						<Timeline entries={recentEntries} />
					{/if}
				</div>

				<div class="right-section">
					<h3 class="section-title">{ng.home_gathering_dust()}</h3>
					{#if staleEntries.length === 0}
						<p class="empty">{ng.home_no_stale()}</p>
					{:else}
						<Timeline entries={staleEntries} />
					{/if}
				</div>

				<div class="right-section">
					<h3 class="section-title"><MapPin size={14} /> {ng.home_by_location()}</h3>
					<div class="location-list">
						{#each locationData as [loc, count], i (loc)}
							<a class="location-item" href={locationBoardHref}>
								<span class="loc-name" use:truncTitle>{loc}</span>
								<span class="loc-badge tier-{tier(i)}">{count} {ng.spool_spool()}</span>
							</a>
						{/each}
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>

{#snippet lowStockRow(row: LowStockRow)}
	<a class="lowstock-item" href={libraryHref('filament', row.filament.id)}>
		<span class="lowstock-left">
			<Swatch
				colors={row.filament.colors}
				direction={row.filament.multiColorDirection}
				size={40}
				radius={6}
			/>
			<span class="lowstock-info">
				<span class="name" use:truncTitle>{getFilamentName(row.filament, vendors)}</span>
				<span class="material">{ng.spool_fields_material()}: {row.filament.material || '?'}</span>
			</span>
		</span>
		<span class="lowstock-right">
			{#if row.onOrder}
				<span class="pill">Ordered · {orderedAge(row.onOrder.orderedAt)}</span>
			{/if}
			<span class="weight" class:actionable={!row.onOrder} class:on-order={!!row.onOrder}>
				{ng.low_stock_remaining_left({ amount: weightAuto(row.remaining) })}
			</span>
		</span>
	</a>
{/snippet}

<style>
	.page {
		max-width: 1400px;
		width: 100%;
		margin: 0 auto;
		padding: 20px 22px 40px;
		display: flex;
		flex-direction: column;
		flex: 1;
		min-height: 0;
	}

	.state {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--text-faint);
		font-size: 13px;
	}
	.state.error {
		flex-direction: column;
		gap: 10px;
		text-align: center;
		color: var(--text-2);
	}
	.state.error h2 {
		margin: 0;
		font-size: 16px;
	}
	.state.error p {
		margin: 0;
		color: var(--text-dim);
		font-size: 13px;
		max-width: 360px;
	}
	.retry {
		margin-top: 6px;
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

	.empty-hero {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		min-height: 60vh;
		text-align: center;
		gap: 0;
	}
	.empty-hero-icon {
		width: 88px;
		height: 88px;
		border-radius: 20px;
		display: flex;
		align-items: center;
		justify-content: center;
		margin-bottom: 28px;
		background: var(--accent-fill);
		color: #fff;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
	}
	.empty-hero h2 {
		font-size: 26px;
		font-weight: 800;
		letter-spacing: -0.03em;
		margin: 0 0 8px 0;
	}
	.empty-hero p {
		font-size: 14px;
		color: var(--text-dim);
		margin: 0 0 32px 0;
		max-width: 400px;
		line-height: 1.6;
	}
	.empty-hero-btn {
		height: 48px;
		padding: 0 32px;
		font-size: 15px;
		font-weight: 700;
		border-radius: 10px;
		letter-spacing: 0.01em;
		border: none;
		background: var(--accent-fill);
		color: #fff;
		cursor: pointer;
		box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
		transition:
			transform 0.15s ease,
			box-shadow 0.15s ease;
	}
	.empty-hero-btn:hover {
		background: var(--accent-fill-hover);
		transform: translateY(-2px);
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
	}

	/* KPI grid */
	.kpi-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 16px;
		margin-bottom: 16px;
		flex-shrink: 0;
	}
	@media (max-width: 1100px) {
		.kpi-grid {
			grid-template-columns: repeat(2, 1fr);
		}
	}
	@media (max-width: 768px) {
		.kpi-grid {
			gap: 8px;
		}
		.kpi-card {
			padding: 12px 14px;
		}
		.kpi-card :global(.kpi-bg-icon) {
			display: none;
		}
		.kpi-card .kpi-value {
			font-size: 22px;
		}
		.kpi-card .kpi-footer {
			margin-top: 8px;
		}
	}

	.kpi-card {
		display: block;
		padding: 20px 24px;
		border-radius: var(--radius-lg);
		background: var(--surface);
		border: 1px solid var(--border);
		position: relative;
		overflow: hidden;
		color: inherit;
		text-decoration: none;
		transition:
			transform 0.2s ease,
			box-shadow 0.2s ease;
	}
	.kpi-card:hover {
		color: inherit;
		transform: translateY(-2px);
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
	}
	.kpi-card:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.kpi-card :global(.kpi-bg-icon) {
		position: absolute;
		right: -4px;
		bottom: -10px;
		width: 80px;
		height: 80px;
		opacity: 0.05;
		pointer-events: none;
		transition: opacity 0.3s ease;
	}
	.kpi-card:hover :global(.kpi-bg-icon) {
		opacity: 0.09;
	}
	.kpi-label {
		font-size: 10px;
		text-transform: uppercase;
		font-weight: 700;
		letter-spacing: 0.12em;
		color: var(--text-faint);
		margin-bottom: 6px;
	}
	.kpi-value {
		font-size: 32px;
		font-weight: 800;
		letter-spacing: -0.03em;
		line-height: 1.1;
	}
	.kpi-unit {
		font-size: 14px;
		font-weight: 400;
		color: var(--text-faint);
	}
	.kpi-footer {
		margin-top: 16px;
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		display: flex;
		align-items: center;
		gap: 4px;
	}
	.kpi-footer.muted {
		color: var(--text-faint);
	}
	.kpi-footer.danger {
		color: var(--danger-soft);
	}

	/* Main content: tabs left, static sections right */
	.main {
		flex: 1 1 0;
		min-height: 0;
		display: grid;
		grid-template-columns: 2fr 1fr;
		gap: 16px;
		overflow: hidden;
	}
	.left {
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	.tabbar {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-bottom: 12px;
		flex-shrink: 0;
	}
	.tab-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 7px 12px;
		border-radius: var(--radius);
		border: none;
		background: none;
		color: var(--text-dim);
		font-size: 13px;
		font-family: inherit;
		cursor: pointer;
		white-space: nowrap;
	}
	.tab-btn:hover {
		color: var(--text);
		background: var(--accent-wash-soft);
	}
	.tab-btn.active {
		font-weight: 600;
		color: var(--accent-soft);
		background: var(--accent-wash);
	}
	.tab-btn :global(.danger) {
		color: var(--danger-soft);
	}
	.panel-wrap {
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}
	.panel {
		height: 100%;
		overflow-y: auto;
		padding: 20px;
		border-radius: var(--radius-lg);
		background: var(--surface);
		border: 1px solid var(--border);
	}

	.empty {
		text-align: center;
		padding: 32px;
		color: var(--text-faint);
		font-size: 13px;
	}

	/* Low stock */
	.subhead {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--text-faint);
		margin: 16px 0 8px;
	}
	.subhead:first-child {
		margin-top: 0;
	}
	.lowstock-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.lowstock-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 12px 14px;
		border-radius: var(--radius);
		background: var(--surface-2);
		color: inherit;
		text-decoration: none;
		transition: background 0.15s ease;
	}
	.lowstock-item:hover {
		background: var(--surface-raised);
	}
	.lowstock-item:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}
	.lowstock-left {
		display: flex;
		align-items: center;
		gap: 14px;
		min-width: 0;
		flex: 1;
	}
	.lowstock-info {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.lowstock-info .name {
		font-size: 13px;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.lowstock-info .material {
		font-size: 11px;
		color: var(--text-faint);
		margin-top: 2px;
	}
	.lowstock-right {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-shrink: 0;
	}
	.pill {
		font-size: 11px;
		font-weight: 600;
		padding: 3px 9px;
		border-radius: 999px;
		background: var(--accent-wash);
		color: var(--accent-soft);
		white-space: nowrap;
	}
	.weight {
		font-size: 13px;
		font-weight: 700;
		white-space: nowrap;
	}
	.weight.actionable {
		color: var(--danger-soft);
	}
	.weight.on-order {
		color: var(--text-faint);
	}

	/* All-spools swatch grid */
	.swatch-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.swatch-item {
		display: block;
		cursor: pointer;
		transition: transform 0.1s ease;
	}
	.swatch-item:hover,
	.swatch-item:focus-visible {
		transform: scale(1.18);
	}

	.bar-list {
		display: flex;
		flex-direction: column;
		gap: 20px;
	}

	/* Right column */
	.right {
		display: flex;
		flex-direction: column;
		gap: 16px;
		min-height: 0;
		/* Aligns with the left column's tab content, which sits below the tab bar. */
		padding-top: 42px;
	}
	.right-section {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 20px;
		border-radius: var(--radius-lg);
		background: var(--surface);
		border: 1px solid var(--border);
	}
	.section-title {
		font-size: 15px;
		font-weight: 700;
		margin: 0 0 18px;
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.location-list {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.location-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		padding: 10px 14px;
		border-radius: var(--radius);
		background: var(--surface-2);
		color: inherit;
		text-decoration: none;
		transition: background 0.15s ease;
	}
	.location-item:hover {
		background: var(--surface-raised);
	}
	.location-item:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}
	.loc-name {
		font-size: 13px;
		font-weight: 500;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.loc-badge {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		padding: 3px 10px;
		border-radius: 4px;
		letter-spacing: 0.02em;
		flex-shrink: 0;
	}
	.loc-badge.tier-0 {
		background: var(--accent-wash);
		color: var(--accent-soft);
	}
	.loc-badge.tier-1 {
		background: color-mix(in srgb, var(--success) 15%, transparent);
		color: var(--success);
	}
	.loc-badge.tier-2 {
		background: var(--surface-raised);
		color: var(--text-faint);
	}

	@media (max-width: 1024px) {
		.main {
			display: flex;
			flex-direction: column;
			overflow: visible;
			flex: none;
			height: auto;
		}
		.panel-wrap {
			overflow: visible;
		}
		.panel {
			height: auto;
			overflow-y: visible;
		}
		.right {
			padding-top: 0;
		}
		.right-section {
			flex: none;
			overflow-y: visible;
		}
	}
</style>
