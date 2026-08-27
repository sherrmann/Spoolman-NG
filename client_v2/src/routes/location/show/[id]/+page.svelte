<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   Every href below goes through libraryHref() from $lib/library/params, which already
	   resolves against the deploy base path; resolving again here would double-apply it. See
	   routes/lowstock/+page.svelte for the same pattern. */
	// The page a scanned `WEB+SPOOLMAN:L-<id>` location label lands on (#103): one Location
	// entity's name, comment, custom-field values and spool count, plus the spools currently AT
	// that location.
	//
	// "Currently at" is found the same way the board (routes/dashboard) does it: by matching
	// `spool.location` -- a plain name STRING -- against this row's own `name`. There is no
	// foreign key between the two (see $lib/ng/types's `Location` doc comment), so this page
	// never writes a spool's location and a rename made on /locations never "moves" anything
	// here -- it just changes which spools this page's filter happens to match.
	//
	// Not the location board: read-only over the spool list, and no drag/drop. It exists for the
	// registry entity and for someone arriving via a scanned label, not for reassigning spools.
	// No print button either -- location label printing is handled separately.
	import { isAbortError, HttpError } from '$lib/api/http';
	import { spoolSource } from '$lib/api/spoolSource';
	import { getLocation, listLocationFields, listAllSpools, listAllFilaments, asFieldDef } from '$lib/ng/api';
	import { ng } from '$lib/ng/i18n';
	import { getFilamentName, getWeightPct } from '$lib/ng/analytics';
	import { weightAuto } from '$lib/utils/format';
	import { libraryHref } from '$lib/library/params';
	import Field from '$components/Field.svelte';
	import FieldGrid from '$components/FieldGrid.svelte';
	import ExtraFieldInput from '$components/ExtraFieldInput.svelte';
	import SectionLabel from '$components/SectionLabel.svelte';
	import ProgressBar from '$components/ProgressBar.svelte';
	import type { Location, ForkFilament } from '$lib/ng/types';
	import type { LocationFieldDef } from '$lib/ng/api';
	import type { Spool, Vendor } from '$lib/types';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	let id = $derived(data.id);

	// --- the location itself + its field definitions ------------------------------------

	let location = $state<Location | undefined>();
	let fieldDefs = $state<LocationFieldDef[]>([]);
	let locationLoaded = $state(false);
	let locationError = $state(false);
	// A stale/mistyped id (an old QR label for a row that's since been deleted) -- distinct
	// from a transient load failure, so the message actually explains what's wrong.
	let notFound = $state(false);

	let locController = new AbortController();

	async function loadLocation(signal: AbortSignal, locId: number) {
		locationError = false;
		notFound = false;
		try {
			const [loc, defs] = await Promise.all([getLocation(locId, signal), listLocationFields(signal)]);
			location = loc;
			fieldDefs = defs;
		} catch (e) {
			if (isAbortError(e, signal)) return;
			if (e instanceof HttpError && e.status === 404) {
				notFound = true;
			} else {
				console.error('Failed to load location', e);
				locationError = true;
			}
		} finally {
			locationLoaded = true;
		}
	}

	function refreshLocation() {
		locController.abort();
		locController = new AbortController();
		loadLocation(locController.signal, id);
	}

	$effect(() => {
		refreshLocation();
		return () => locController.abort();
	});

	// --- spools currently at this location -----------------------------------------------

	let spools = $state<Spool[]>([]);
	let filaments = $state<ForkFilament[]>([]);
	let vendors = $state<Vendor[]>([]);
	let spoolsLoaded = $state(false);
	let spoolsError = $state(false);

	let spoolController = new AbortController();

	async function loadSpools(signal: AbortSignal) {
		try {
			const [s, f, v] = await Promise.all([
				listAllSpools(signal),
				listAllFilaments(signal),
				spoolSource.listVendors(signal)
			]);
			spools = s;
			filaments = f;
			vendors = v;
			spoolsError = false;
		} catch (e) {
			if (isAbortError(e, signal)) return;
			console.error('Failed to load spools', e);
			spoolsError = true;
		} finally {
			spoolsLoaded = true;
		}
	}

	function refreshSpools() {
		spoolController.abort();
		spoolController = new AbortController();
		loadSpools(spoolController.signal);
	}

	// Loaded once on mount -- unlike the location itself, the full spool list doesn't depend on
	// `id`, only the filter below does.
	$effect(() => {
		refreshSpools();
		return () => spoolController.abort();
	});

	// Matched by NAME, not id -- see the file-top comment. `loc` is captured in a snapshot so
	// TypeScript doesn't have to re-narrow `location` (a $state) as possibly-undefined inside
	// the filter callback.
	let spoolsHere = $derived.by(() => {
		const loc = location;
		return loc ? spools.filter((s) => s.location === loc.name) : [];
	});

	function filamentFor(spool: Spool): ForkFilament | undefined {
		return filaments.find((f) => f.id === spool.filamentId);
	}
</script>

<svelte:head>
	<title>{location ? location.name : ng.locations_location()} | Spoolman</title>
</svelte:head>

<div class="page scroll-y">
	{#if !locationLoaded}
		<div class="state">{ng.loading()}</div>
	{:else if notFound}
		<div class="state">
			<!-- No dedicated ng.* string for "this id doesn't exist" (as opposed to a transient
			     load failure, which locations_fields_load_error covers) -- hardcoded English. -->
			<p>{ng.locations_show_not_found()}</p>
		</div>
	{:else if locationError}
		<div class="state error">
			<p>{ng.locations_fields_load_error()}</p>
			<button class="retry" onclick={refreshLocation}>{ng.buttons_refresh()}</button>
		</div>
	{:else if location}
		<div class="header">
			<h1>{location.name}</h1>
		</div>

		<FieldGrid>
			<Field label={ng.locations_show_comment()}>
				<span>{location.comment || '—'}</span>
			</Field>
			<Field label={ng.locations_show_spool_count()}>
				<span class="mono">{location.spoolCount ?? spoolsHere.length}</span>
			</Field>
		</FieldGrid>

		{#if fieldDefs.length > 0}
			<div>
				<SectionLabel>{ng.settings_extra_fields_tab()}</SectionLabel>
				<FieldGrid>
					{#each fieldDefs as def (def.key)}
						<Field label={def.name}>
							<ExtraFieldInput
								field={asFieldDef(def)}
								value={location.extra[def.key]}
								onchange={() => {}}
								readonly
							/>
						</Field>
					{/each}
				</FieldGrid>
			</div>
		{/if}

		<div>
			<SectionLabel>{ng.locations_show_spools_here()}</SectionLabel>

			{#if !spoolsLoaded}
				<div class="state">{ng.loading()}</div>
			{:else if spoolsError}
				<div class="state error">
					<p>{ng.locations_load_error()}</p>
					<button class="retry" onclick={refreshSpools}>{ng.buttons_refresh()}</button>
				</div>
			{:else if spoolsHere.length === 0}
				<p class="empty">{ng.locations_show_no_spools()}</p>
			{:else}
				<div class="columns-header">
					<span class="ch-id">{ng.spool_fields_id()}</span>
					<span class="ch-filament">{ng.spool_fields_filament()}</span>
					<span class="ch-weight">{ng.spool_fields_remaining_weight()}</span>
				</div>
				<ul class="list">
					{#each spoolsHere as spool (spool.id)}
						{@const filament = filamentFor(spool)}
						<li class="row">
							<!-- Stretched-row link: `.row` is position:relative, `.spool-link` carries the
							     visible content and its ::after covers the whole row. No other interactive
							     element sits in this row, so nothing else needs raising above it. -->
							<a class="spool-link" href={libraryHref('spool', String(spool.id))}>
								<span class="spool-id mono">#{spool.id}</span>
								<span class="spool-name">{filament ? getFilamentName(filament, vendors) : '—'}</span>
								<span class="spool-weight">
									<ProgressBar value={filament ? getWeightPct(spool) : 0} width="40px" height={4} />
									<span class="mono">{weightAuto(spool.remaining)}</span>
								</span>
							</a>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	{/if}
</div>

<style>
	.page {
		max-width: 900px;
		width: 100%;
		margin: 0 auto;
		padding: 20px 22px 40px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.header h1 {
		margin: 0 0 16px;
		font-size: 20px;
		font-weight: 800;
		letter-spacing: -0.02em;
	}

	.state {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		padding: 48px 0;
		color: var(--text-faint);
		font-size: 13px;
	}
	.state.error p {
		margin: 0;
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
		padding: 32px 0;
		color: var(--text-faint);
		font-size: 13px;
	}

	.columns-header {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 0 16px 8px;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-faint);
	}
	.ch-id {
		width: 60px;
		flex: none;
	}
	.ch-filament {
		flex: 1;
	}
	.ch-weight {
		width: 120px;
		flex: none;
		text-align: right;
	}

	.list {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.row {
		position: relative;
		border-radius: var(--radius-lg);
		background: var(--surface);
		border: 1px solid var(--border);
	}
	.row:hover {
		background: var(--surface-raised);
	}

	.spool-link {
		display: flex;
		align-items: center;
		gap: 16px;
		width: 100%;
		padding: 12px 16px;
		color: inherit;
		text-decoration: none;
	}
	.spool-link::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: inherit;
	}
	.spool-link:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.spool-id {
		width: 60px;
		flex: none;
		color: var(--text-faint);
		font-size: 12.5px;
	}
	.spool-name {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 13.5px;
		font-weight: 600;
	}
	.spool-weight {
		width: 120px;
		flex: none;
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		font-size: 12.5px;
	}

	@media (max-width: 600px) {
		.ch-id,
		.spool-id {
			display: none;
		}
		.spool-weight :global(.track) {
			display: none;
		}
	}
</style>
