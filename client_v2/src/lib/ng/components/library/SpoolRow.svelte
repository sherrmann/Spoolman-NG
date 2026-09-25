<script lang="ts">
	/**
	 * Spoolman NG fork seam (#412): upstream's library row, plus a checkbox while selecting.
	 *
	 * The three upstream components that render a spool row import this file instead of
	 * upstream's (see the Tier 2 table in docs/upstream/client-v2-fork-additions.md), so every
	 * place a spool row appears gets the checkbox without any of their templates changing.
	 *
	 * With selection off this renders upstream's row and nothing else, so the DOM is upstream's
	 * and the vendored Playwright suite sees exactly what it was written against. With selection
	 * on, the checkbox is a SIBLING of the row's link: an <input> inside an <a> is invalid HTML.
	 * The low-stock page solved the same problem the same way.
	 *
	 * In gallery mode (#412 step 3) it renders a card instead, which carries its own checkbox.
	 * In the flat list with columns configured (step 5) it renders the fork's cell row.
	 */
	import type { ComponentProps } from 'svelte';
	import Upstream from '$components/library/SpoolRow.svelte';
	import { librarySelection } from '$lib/ng/librarySelection.svelte';
	import { ng } from '$lib/ng/i18n';
	import { libraryMode } from '$lib/ng/libraryMode.svelte';
	import SpoolCard from './SpoolCard.svelte';
	import SpoolCells from './SpoolCells.svelte';
	import { columnsView } from '$lib/ng/libraryColumnsView.svelte';

	let props: ComponentProps<typeof Upstream> = $props();

	// Registered whether or not selection is on, so "select all shown" knows what is on screen
	// the moment the mode is switched on. Re-runs when the row gets a newer view model.
	$effect(() => librarySelection.register(props.vm));
</script>

{#if libraryMode.mode === 'gallery'}
	<SpoolCard vm={props.vm} context={props.context} />
{:else if columnsView.custom && (props.context ?? 'flat') === 'flat'}
	<SpoolCells vm={props.vm} />
{:else if librarySelection.on}
	<div class="ng-row">
		<span class="check" style="padding-left:{Math.max(0, (props.indent ?? 14) - 6)}px">
			<input
				type="checkbox"
				checked={librarySelection.has(props.vm.spool.id)}
				aria-label={ng.spool_bulk_select_row({ id: props.vm.spool.id })}
				onchange={() => librarySelection.toggle(props.vm)}
			/>
		</span>
		<Upstream {...props} indent={6} />
	</div>
{:else}
	<Upstream {...props} />
{/if}

<style>
	.ng-row {
		display: flex;
		align-items: stretch;
		border-top: 1px solid var(--hairline);
	}
	/* The wrapper carries the hairline, so the row inside must not draw a second one. If
	   upstream renames `.row` the symptom is a doubled hairline, not a broken list. */
	.ng-row > :global(.row) {
		border-top: none;
		min-width: 0;
	}
	.check {
		flex: none;
		display: flex;
		align-items: center;
	}
	.check input {
		accent-color: var(--accent);
		margin: 0;
	}
</style>
