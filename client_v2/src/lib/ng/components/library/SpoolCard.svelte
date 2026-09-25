<script lang="ts">
	/**
	 * Spoolman NG fork addition (#412 step 3): a spool as a card, for browsing the Library by
	 * colour.
	 *
	 * The card is the same link the row is (`?sel=spool:<id>`), with the same identity text: under
	 * a filament group it does not repeat the filament. Cards are inline blocks, so they flow and
	 * wrap inside upstream's list container and under each group header without any change to
	 * the list components. The checkbox, while selecting, is a sibling of the link, never inside
	 * it, for the same reason as the row's.
	 */
	/* eslint-disable svelte/no-navigation-without-resolve --
	   The href comes from a params.ts helper, which already resolves against the base path. */
	import Swatch from '$components/Swatch.svelte';
	import ProgressBar from '$components/ProgressBar.svelte';
	import * as params from '$lib/library/params';
	import { page } from '$app/state';
	import * as m from '$lib/paraglide/messages';
	import { rowIdentity, type RowContext, type SpoolVM } from '$lib/utils/library';
	import { truncTitle } from '$lib/actions/truncated';
	import { librarySelection } from '$lib/ng/librarySelection.svelte';
	import { ng } from '$lib/ng/i18n';

	interface Props {
		vm: SpoolVM;
		context?: RowContext;
	}
	let { vm, context = 'flat' }: Props = $props();

	let identity = $derived(rowIdentity(vm, context));
	let id = $derived(String(vm.spool.id));
	let selected = $derived(params.isSelected(page.url.searchParams, 'spool', id));
</script>

<div class="ng-card" class:ticked={librarySelection.on && librarySelection.has(vm.spool.id)}>
	<a
		class="card"
		class:selected
		class:archived={vm.spool.archived}
		href={params.selectHref(page.url.searchParams, 'spool', id)}
		data-sveltekit-keepfocus
		data-sveltekit-noscroll
	>
		<span class="top">
			<Swatch colors={vm.filament.colors} direction={vm.filament.multiColorDirection} size={56} />
			<span class="id mono">{vm.idLabel}</span>
		</span>
		<span class="name">
			{#if identity.title}<span class="title" use:truncTitle>{identity.title}</span>{/if}
			{#if identity.sub}<span class="sub" use:truncTitle>{identity.sub}</span>{/if}
		</span>
		<span class="facts">
			<span class="rem mono" class:low={vm.low}>{vm.remLabel}</span>
			{#if vm.spool.archived}
				<span class="tag">{m['spool.fields.archived']()}</span>
			{:else if vm.location}
				<span class="loc" use:truncTitle>{vm.location}</span>
			{/if}
		</span>
		<span class="gauge"><ProgressBar value={vm.pctValue} danger={vm.low} width="100%" height={3} /></span>
	</a>
	{#if librarySelection.on}
		<input
			class="check"
			type="checkbox"
			checked={librarySelection.has(vm.spool.id)}
			aria-label={ng.spool_bulk_select_row({ id: vm.spool.id })}
			onchange={() => librarySelection.toggle(vm)}
		/>
	{/if}
</div>

<style>
	/* Inline, not flex items: the list container is a plain block, so inline blocks wrap into a
	   grid inside it and under each group header without anything upstream changing. If upstream
	   ever turns the container into a flex column, cards stack one per line; the gallery spec
	   checks that two cards share a line. */
	.ng-card {
		position: relative;
		display: inline-block;
		vertical-align: top;
		width: 168px;
		margin: 6px 0 0 8px;
	}
	.card {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 10px 10px 0;
		border: 1px solid var(--border);
		border-radius: var(--radius-md);
		background: var(--bg);
		color: inherit;
		text-decoration: none;
		overflow: hidden;
	}
	.card:hover {
		background: var(--surface-2);
	}
	.card.selected {
		background: var(--accent-wash);
		border-color: var(--accent);
	}
	.ng-card.ticked .card {
		border-color: var(--accent-border);
	}
	.card.archived .top,
	.card.archived .name {
		opacity: 0.55;
	}
	.top {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
	}
	.id {
		font-size: 11px;
		color: var(--text-muted);
	}
	.name {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 46px;
	}
	.sub {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	/* Two lines, not one: the colour name usually comes last ("Prusament Galaxy Black"), and
	   browsing by colour is what the gallery is for. */
	.title {
		font-weight: 600;
		font-size: 12.5px;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		overflow: hidden;
		overflow-wrap: anywhere;
	}
	.sub {
		font-size: 11px;
		color: var(--text-dim);
	}
	.facts {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 6px;
		font-size: 11px;
	}
	.rem {
		color: var(--text-2);
		white-space: nowrap;
	}
	.rem.low {
		color: var(--danger-soft);
	}
	.loc {
		min-width: 0;
		color: var(--text-dim);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.tag {
		font-size: 9.5px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-dim);
		border: 1px solid var(--border-soft);
		border-radius: var(--radius-sm);
		padding: 1px 5px;
	}
	/* The gauge runs along the bottom edge, as on the dashboard's location chips. */
	.gauge {
		display: block;
		margin: 0 -10px;
	}
	.check {
		position: absolute;
		top: 8px;
		right: 8px;
		margin: 0;
		accent-color: var(--accent);
	}
	/* With the checkbox in the top-right corner, the id moves out of its way. */
	.ng-card:has(.check) .id {
		margin-right: 20px;
	}
</style>
