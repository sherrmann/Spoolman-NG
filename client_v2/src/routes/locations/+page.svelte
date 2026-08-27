<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   showHref() below always returns resolve(...)'s own result; resolving it again here would
	   double-apply the deploy base path. See routes/lowstock/+page.svelte for the same pattern. */
	// Location entity REGISTRY (#103): list / create / rename / delete Location rows, and edit
	// their custom fields. NOT the location board -- routes/dashboard already groups spools by
	// their plain `Spool.location` STRING and drags them between columns. This page manages the
	// separate registry of Location ENTITIES (`/api/v1/locations`) that a name can be matched
	// against to carry custom fields and a scannable identity. See $lib/ng/types's `Location` doc
	// comment for why the two don't share a foreign key.
	//
	// Data loading/live-refresh follows routes/orders/+page.svelte's own pattern (an
	// AbortController-guarded load plus a debounced live subscription) rather than a
	// per-resource cache, since this client has none for this fork's own aggregates. Only the
	// `spool` channel is subscribed -- a spool moving in or out changes a row's `spool_count`,
	// and Locations themselves have no live channel of their own (see $lib/api/live's Resource
	// union): a create/rename/delete here calls refresh() directly on success instead.
	import { resolve } from '$app/paths';
	import { live } from '$lib/api/live';
	import { isAbortError } from '$lib/api/http';
	import {
		listLocations,
		listLocationFields,
		deleteLocation,
		updateLocation,
		type LocationFieldDef
	} from '$lib/ng/api';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import type { Location } from '$lib/ng/types';
	import Button from '$components/Button.svelte';
	import ConfirmDialog from '$components/ConfirmDialog.svelte';
	import NewLocationModal from '$lib/ng/components/NewLocationModal.svelte';
	import LocationFieldsModal from '$lib/ng/components/LocationFieldsModal.svelte';
	import Check from '@lucide/svelte/icons/check';
	import X from '@lucide/svelte/icons/x';
	import Pencil from '@lucide/svelte/icons/pencil';

	// --- data loading ----------------------------------------------------------------

	let locations = $state<Location[]>([]);
	let fieldDefs = $state<LocationFieldDef[]>([]);

	let loaded = $state(false);
	let loadError = $state(false);

	let controller = new AbortController();

	async function loadAll(signal: AbortSignal) {
		try {
			const [l, f] = await Promise.all([listLocations(signal), listLocationFields(signal)]);
			locations = l;
			fieldDefs = f;
			loadError = false;
		} catch (e) {
			if (isAbortError(e, signal)) return;
			console.error('Failed to load locations', e);
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
		let timer: ReturnType<typeof setTimeout> | null = null;
		const scheduleRefresh = () => {
			if (timer) clearTimeout(timer);
			timer = setTimeout(() => {
				timer = null;
				refresh();
			}, 400);
		};
		const offSpool = live.subscribe('spool', {}, scheduleRefresh);
		return () => {
			offSpool();
			if (timer) clearTimeout(timer);
			controller.abort();
		};
	});

	// Gates the per-row "Custom fields" button: a site with no location field DEFINITIONS at
	// all sees a plain list, rather than a button that always opens an empty dialog.
	let hasFieldDefs = $derived(fieldDefs.length > 0);

	function showHref(id: number): string {
		return resolve(`/location/show/${id}`);
	}

	// --- create ------------------------------------------------------------------------

	let creating = $state(false);

	// --- rename (inline, click-the-name) ------------------------------------------------

	let renamingId = $state<number | null>(null);
	let renameDraft = $state('');
	let renameError = $state('');
	let renameSubmitting = $state(false);

	function startRename(loc: Location) {
		renamingId = loc.id;
		renameDraft = loc.name;
		renameError = '';
	}
	function cancelRename() {
		renamingId = null;
		renameError = '';
	}

	async function submitRename(loc: Location) {
		if (renameSubmitting) return;
		const trimmed = renameDraft.trim();
		if (!trimmed) {
			renameError = ng.locations_error_empty();
			return;
		}
		if (locations.some((l) => l.id !== loc.id && l.name === trimmed)) {
			renameError = ng.locations_error_exists();
			return;
		}
		if (trimmed === loc.name) {
			// Nothing actually changed -- close the editor rather than issue a no-op PATCH.
			renamingId = null;
			return;
		}
		renameSubmitting = true;
		try {
			// Renaming the registry row touches ONLY this row's own `name` column. It does NOT
			// walk existing spools and rewrite their `location` string to match the new name --
			// that string is the board's (routes/dashboard) to own, and a spool is matched to a
			// registry row by reading the SPOOL's string, never the other way around. So a
			// rename here quietly detaches this row from whatever spools matched the old name
			// (they still say the old name, and now match nothing, or a different row someone
			// else created with that name). That is the correct behaviour, not a bug this page
			// should "fix" by cascading the rename onto spools it doesn't own.
			await updateLocation(loc.id, { name: trimmed });
			renamingId = null;
			refresh();
		} catch (e) {
			console.error('Failed to rename location', e);
			renameError = ng.locations_rename_error();
		} finally {
			renameSubmitting = false;
		}
	}

	// --- delete --------------------------------------------------------------------------

	let deletingLoc = $state<Location | undefined>();
	let deleting = $state(false);

	async function doDelete() {
		if (!deletingLoc) return;
		deleting = true;
		try {
			await deleteLocation(deletingLoc.id);
			deletingLoc = undefined;
			refresh();
		} catch (e) {
			console.error('Failed to delete location', e);
			toasts.error(ng.locations_delete_error());
		} finally {
			deleting = false;
		}
	}

	// --- custom fields modal ---------------------------------------------------------------

	let editingFieldsFor = $state<Location | undefined>();

	function fieldsSaved() {
		editingFieldsFor = undefined;
		refresh();
	}
</script>

<svelte:head>
	<title>{ng.locations_locations()} | Spoolman</title>
</svelte:head>

<div class="page scroll-y">
	<div class="header">
		<h1>{ng.locations_locations()}</h1>
		<Button onclick={() => (creating = true)}>{ng.locations_new_location()}</Button>
	</div>

	{#if !loaded}
		<div class="state">{ng.loading()}</div>
	{:else if loadError}
		<div class="state error">
			<button class="retry" onclick={refresh}>{ng.buttons_refresh()}</button>
		</div>
	{:else if locations.length === 0}
		<p class="empty">{ng.locations_empty()}</p>
	{:else}
		<ul class="list">
			{#each locations as loc (loc.id)}
				{@const canDelete = (loc.spoolCount ?? 0) === 0}
				<li class="row">
					<div class="row-main">
						{#if renamingId === loc.id}
							<form
								class="rename-form"
								onsubmit={(e) => {
									e.preventDefault();
									submitRename(loc);
								}}
							>
								<input
									class="rename-input"
									bind:value={renameDraft}
									aria-label={ng.locations_location()}
									disabled={renameSubmitting}
									class:invalid={!!renameError}
									aria-invalid={!!renameError}
								/>
								<button
									type="submit"
									class="rename-btn"
									disabled={renameSubmitting}
									aria-label={ng.buttons_save()}><Check size={14} /></button
								>
								<button
									type="button"
									class="rename-btn"
									onclick={cancelRename}
									disabled={renameSubmitting}
									aria-label={ng.buttons_cancel()}><X size={14} /></button
								>
							</form>
							{#if renameError}<span class="inline-error" role="alert">{renameError}</span>{/if}
						{:else}
							<!-- The row's stretched hit target: an <a> over the location's own NAME whose
							     ::after covers the whole <li> (`.row` is position:relative), exactly as
							     routes/lowstock and routes/orders do it. The name is the link and not the
							     rename trigger deliberately: on this page the name's primary meaning is
							     "open this location", and rename is the secondary action (the pencil in
							     .row-right). The React board reads the other way round -- click the column
							     title to rename -- because a board column has no detail page to open. -->
							<a class="name" href={showHref(loc.id)}>{loc.name}</a>
						{/if}
						{#if loc.comment}<span class="comment" title={loc.comment}>{loc.comment}</span>{/if}
					</div>
					<div class="row-right">
						<span class="count">{loc.spoolCount ?? 0}</span>
						{#if hasFieldDefs}
							<Button variant="outline" onclick={() => (editingFieldsFor = loc)}>
								{ng.locations_fields_button()}
							</Button>
						{/if}
						<button
							type="button"
							class="icon-btn"
							onclick={() => startRename(loc)}
							title={ng.buttons_edit()}
							aria-label={ng.buttons_edit()}><Pencil size={14} /></button
						>
						{#if canDelete}
							<Button variant="danger-ghost" onclick={() => (deletingLoc = loc)}>
								{ng.buttons_delete()}
							</Button>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</div>

{#if creating}
	<NewLocationModal
		existingNames={locations.map((l) => l.name)}
		onclose={() => (creating = false)}
		onsuccess={refresh}
	/>
{/if}

{#if editingFieldsFor}
	<LocationFieldsModal
		location={editingFieldsFor}
		defs={fieldDefs}
		onclose={() => (editingFieldsFor = undefined)}
		onsuccess={fieldsSaved}
	/>
{/if}

<ConfirmDialog
	open={!!deletingLoc}
	title={deletingLoc?.name ?? ''}
	lines={[ng.buttons_confirm()]}
	confirmLabel={ng.buttons_delete()}
	busy={deleting}
	onconfirm={doDelete}
	onclose={() => (deletingLoc = undefined)}
/>

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
	}

	/* Stretched-row pattern: `.row` is the positioned ancestor that `.name::after` covers via
	   inset:0, and every other interactive element in the row (the rename editor and
	   `.row-right`'s buttons) is raised above it with position + z-index. */
	.row {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		width: 100%;
		padding: 12px 16px;
		border-radius: var(--radius-lg);
		background: var(--surface);
		border: 1px solid var(--border);
	}
	.row:hover {
		background: var(--surface-raised);
	}

	.row-main {
		display: flex;
		align-items: baseline;
		gap: 12px;
		min-width: 0;
		flex: 1;
	}

	/* The stretched link. `.name` must NOT be positioned: its ::after is what covers the whole
	   row, and `position: relative` here would confine that ::after to the name text itself --
	   measured, not assumed (routes/orders shipped exactly that bug: a mid-row click landed on
	   `.lines-summary` and did nothing). `.row` is the positioned ancestor; only the controls
	   that must sit ABOVE the ::after carry position + z-index. */
	.name {
		flex: none;
		font-size: 13.5px;
		font-weight: 600;
		color: var(--text);
		text-decoration: none;
	}
	.name::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: inherit;
	}
	.name:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}

	.comment {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 12px;
		color: var(--text-faint);
	}

	.rename-form {
		position: relative;
		z-index: 1;
		display: flex;
		align-items: center;
		gap: 6px;
		flex: none;
	}
	.rename-input {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 4px 8px;
		font-size: 13px;
		width: 180px;
		max-width: 40vw;
	}
	.rename-input:focus {
		border-color: var(--accent);
	}
	.rename-input.invalid {
		border-color: var(--danger);
	}
	.rename-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-sm);
		color: var(--text-dim);
		padding: 5px;
		cursor: pointer;
	}
	.rename-btn:hover {
		color: var(--text);
		background: var(--surface-raised);
	}
	.inline-error {
		position: relative;
		z-index: 1;
		flex: none;
		font-size: 11.5px;
		color: var(--danger-soft);
	}

	.row-right {
		position: relative;
		z-index: 1;
		display: flex;
		align-items: center;
		gap: 12px;
		flex-shrink: 0;
	}
	.count {
		min-width: 24px;
		text-align: right;
		font-size: 13px;
		font-weight: 700;
		color: var(--text-2);
	}

	/* Inside `.row-right`, so already raised above the stretched ::after. */
	.icon-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 4px;
		border: none;
		border-radius: var(--radius);
		background: none;
		color: var(--text-faint);
		cursor: pointer;
	}
	.icon-btn:hover {
		color: var(--text);
		background: var(--surface-raised);
	}

	@media (max-width: 640px) {
		.row {
			flex-wrap: wrap;
		}
		.comment {
			display: none;
		}
	}
</style>
