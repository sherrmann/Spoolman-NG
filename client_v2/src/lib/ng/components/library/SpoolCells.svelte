<script lang="ts">
	/**
	 * Spoolman NG fork addition (#412 step 5): a spool row drawn from the user's chosen columns.
	 *
	 * Used by the row seam only in the flat list and only once columns have been configured, so an
	 * install that never touches the column manager keeps upstream's row. Like that row, it is one
	 * select link; the selection checkbox sits beside it, never inside it. Every row and the
	 * header share one grid template (libraryColumnsView), so the columns line up.
	 */
	/* eslint-disable svelte/no-navigation-without-resolve --
	   The href comes from a params.ts helper, which already resolves against the base path. */
	import Swatch from '$components/Swatch.svelte';
	import ProgressBar from '$components/ProgressBar.svelte';
	import * as params from '$lib/library/params';
	import { page } from '$app/state';
	import { rowIdentity, type SpoolVM } from '$lib/utils/library';
	import { weightAuto } from '$lib/utils/format';
	import { settings } from '$lib/stores/settings.svelte';
	import { librarySelection } from '$lib/ng/librarySelection.svelte';
	import { columnsView } from '$lib/ng/libraryColumnsView.svelte';
	import { CATALOGUE_COLUMNS, EXTRA_PREFIX } from '$lib/ng/libraryColumnCatalogue';
	import { catalogueText } from '$lib/ng/filamentCatalogueText';
	import type { FilamentNg } from '$lib/ng/filamentCatalogue';
	import { ng } from '$lib/ng/i18n';

	interface Props {
		vm: SpoolVM;
	}
	let { vm }: Props = $props();

	let id = $derived(String(vm.spool.id));
	let selected = $derived(params.isSelected(page.url.searchParams, 'spool', id));
	let identity = $derived(rowIdentity(vm, 'flat'));
	let price = $derived(vm.spool.price ?? vm.filament.price);

	/** An extra field's stored value is JSON; show it as the text it stands for. */
	function extraText(key: string): string {
		const raw = vm.spool.extra[key];
		if (raw === undefined || raw === '') return '';
		try {
			const v: unknown = JSON.parse(raw);
			if (v === null) return '';
			if (Array.isArray(v)) return v.join(', ');
			if (typeof v === 'boolean') return v ? '✓' : '✗';
			return String(v);
		} catch {
			return raw;
		}
	}
</script>

<div class="ng-cells-row">
	{#if librarySelection.on}
		<span class="check">
			<input
				type="checkbox"
				checked={librarySelection.has(vm.spool.id)}
				aria-label={ng.spool_bulk_select_row({ id: vm.spool.id })}
				onchange={() => librarySelection.toggle(vm)}
			/>
		</span>
	{/if}
	<a
		class="cells"
		class:selected
		class:archived={vm.spool.archived}
		style="grid-template-columns:{columnsView.template};min-width:{columnsView.minWidth}px"
		href={params.selectHref(page.url.searchParams, 'spool', id)}
		data-sveltekit-keepfocus
		data-sveltekit-noscroll
	>
		{#each columnsView.visible as col (col)}
			<span class="cell" class:right={columnsView.byId.get(col)?.align === 'right'} data-col={col}>
				{#if col === 'id'}
					<span class="mono dim">{vm.idLabel}</span>
				{:else if col === 'swatch'}
					<Swatch colors={vm.filament.colors} direction={vm.filament.multiColorDirection} size={18} />
				{:else if col === 'name'}
					<span class="name" title={[identity.title, identity.sub].filter(Boolean).join(' · ')}>
						{#if identity.title}<span class="title">{identity.title}</span>{/if}
						{#if identity.sub}<span class="sub">{identity.sub}</span>{/if}
					</span>
				{:else if col === 'material'}
					{vm.filament.material}
				{:else if col === 'vendor'}
					{vm.vendor.name}
				{:else if col === 'diameter'}
					<span class="mono">{vm.filament.diameter ? `${vm.filament.diameter} mm` : ''}</span>
				{:else if col === 'progress'}
					<ProgressBar value={vm.pctValue} danger={vm.low} width="100%" />
				{:else if col === 'remaining'}
					<span class="mono" class:low={vm.low}>{vm.remLabel}</span>
				{:else if col === 'used'}
					<span class="mono">{weightAuto(vm.spool.usedWeight)}</span>
				{:else if col === 'price'}
					<span class="mono">{price > 0 ? settings.formatPrice(price) : ''}</span>
				{:else if col === 'lot'}
					{vm.spool.lot}
				{:else if col === 'location'}
					{vm.spool.location}
				{:else if col === 'firstUsed'}
					{vm.spool.firstUsedLabel}
				{:else if col === 'lastUsed'}
					{vm.spool.lastUsedLabel}
				{:else if col === 'registered'}
					{vm.spool.registeredLabel}
				{:else if col === 'comment'}
					<span title={vm.spool.comment}>{vm.spool.comment}</span>
				{:else if CATALOGUE_COLUMNS.has(col)}
					{catalogueText(col as keyof FilamentNg, vm.filament.ng)}
				{:else if col.startsWith(EXTRA_PREFIX)}
					{extraText(col.slice(EXTRA_PREFIX.length))}
				{/if}
			</span>
		{/each}
	</a>
</div>

<style>
	.ng-cells-row {
		display: flex;
		align-items: stretch;
		border-top: 1px solid var(--hairline);
	}
	.check {
		flex: none;
		width: 22px;
		display: flex;
		align-items: center;
		justify-content: flex-end;
	}
	.check input {
		margin: 0;
		accent-color: var(--accent);
	}
	/* Padding and gap match ColumnHeader's, which is what keeps the two in line. */
	.cells {
		flex: 1;
		min-width: 0;
		display: grid;
		align-items: center;
		column-gap: 9px;
		padding: 7px 14px;
		border-left: 2px solid transparent;
		color: inherit;
		text-decoration: none;
		font-size: 12px;
	}
	.cells:hover {
		background: var(--surface-2);
	}
	.cells.selected {
		background: var(--accent-wash);
		border-left-color: var(--accent);
	}
	.cells.archived {
		opacity: 0.55;
	}
	.cell {
		min-width: 0;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}
	.cell.right {
		text-align: right;
	}
	.name {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.title,
	.sub {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.title {
		font-weight: 600;
		font-size: 12.5px;
	}
	.sub,
	.dim {
		font-size: 11px;
		color: var(--text-dim);
	}
	.mono {
		font-size: 11px;
	}
	.low {
		color: var(--danger-soft);
	}
</style>
