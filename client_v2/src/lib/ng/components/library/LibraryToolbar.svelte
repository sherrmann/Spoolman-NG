<script lang="ts">
	/**
	 * Spoolman NG fork seam (#412 step 5): upstream's toolbar, then the column header when the
	 * flat list is showing configured columns.
	 *
	 * FilamentList imports this in place of upstream's ListToolbar (Tier 2), because the header has
	 * to sit between the toolbar and the scrolling list, and that is the only place to reach it
	 * without editing FilamentList's template. Every prop is forwarded unchanged.
	 */
	import type { ComponentProps } from 'svelte';
	import ListToolbar from '$components/library/ListToolbar.svelte';
	import ColumnHeader from './ColumnHeader.svelte';
	import { isGroupedMode } from '$lib/api/query';
	import { fields } from '$lib/stores/fields.svelte';
	import { libraryMode } from '$lib/ng/libraryMode.svelte';
	import { columnsView } from '$lib/ng/libraryColumnsView.svelte';

	let props: ComponentProps<typeof ListToolbar> = $props();

	let showHeader = $derived(
		columnsView.custom && libraryMode.mode === 'list' && !isGroupedMode(props.libraryState)
	);

	// Extra fields are columns too, so their definitions are needed as soon as columns are.
	$effect(() => {
		if (columnsView.custom) fields.ensure('spool');
	});
</script>

<ListToolbar {...props} />
{#if showHeader}
	<ColumnHeader />
{/if}
