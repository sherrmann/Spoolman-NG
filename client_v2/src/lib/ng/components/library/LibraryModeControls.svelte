<script lang="ts">
	/**
	 * Spoolman NG fork addition (#412): the "Select" chip in the Library toolbar, and "Select all
	 * shown" while it is on. Mounted beside NlSearchButton, in a hunk this fork already owns.
	 *
	 * The selection lives exactly as long as this component: the toolbar is on screen for as long
	 * as the Library is, so unmounting here is what drops a selection when the user leaves.
	 *
	 * Also the list/gallery switch (#412 step 3), which is a remembered layout preference.
	 */
	import CheckSquare from '@lucide/svelte/icons/square-check';
	import LayoutGrid from '@lucide/svelte/icons/layout-grid';
	import { libraryMode } from '$lib/ng/libraryMode.svelte';
	import { librarySelection } from '$lib/ng/librarySelection.svelte';
	import { ng } from '$lib/ng/i18n';

	$effect(() => () => librarySelection.setMode(false));
</script>

<button
	class="trigger"
	class:active={libraryMode.mode === 'gallery'}
	aria-pressed={libraryMode.mode === 'gallery'}
	title={libraryMode.mode === 'gallery' ? ng.spool_view_table_tooltip() : ng.spool_view_grid_tooltip()}
	onclick={() => libraryMode.set(libraryMode.mode === 'gallery' ? 'list' : 'gallery')}
>
	<LayoutGrid size={14} />
	{ng.spool_view_grid()}
</button>
<button
	class="trigger"
	class:active={librarySelection.on}
	aria-pressed={librarySelection.on}
	onclick={() => librarySelection.setMode(!librarySelection.on)}
>
	<CheckSquare size={14} />
	{ng.spool_bulk_select_mode()}
</button>
{#if librarySelection.on}
	<button class="trigger" onclick={() => librarySelection.selectShown()}>
		{ng.spool_bulk_select_shown()}
	</button>
{/if}

<style>
	/* The same look as NlSearchButton's trigger, the other fork control in this row. */
	.trigger {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 5px 9px;
		font-size: 12px;
		color: var(--text-muted);
		background: var(--bg-subtle);
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		white-space: nowrap;
	}
	.trigger:hover {
		color: var(--text);
		border-color: var(--border-strong);
	}
	.trigger.active {
		background: var(--accent-wash);
		border-color: var(--accent-border);
		color: var(--accent-soft);
	}
</style>
