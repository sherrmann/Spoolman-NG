<script lang="ts">
	/**
	 * Spoolman NG fork addition (#412 step 5): the header row over configured columns, with a
	 * resize handle on each column's right edge (drag it, or focus it and use the arrow keys).
	 *
	 * Rendered by LibraryToolbar above the list, only in the flat list with columns configured.
	 * It shares its grid template, padding and gap with SpoolCells; widths are saved when a drag
	 * ends, not on every pointer move.
	 */
	import { librarySelection } from '$lib/ng/librarySelection.svelte';
	import { libraryColumns } from '$lib/ng/libraryColumns.svelte';
	import { columnsView } from '$lib/ng/libraryColumnsView.svelte';
	import { ng } from '$lib/ng/i18n';

	const STEP = 10;

	// More columns than the pane is wide: the list below scrolls sideways (see the style block),
	// and the header, which sits outside that scroll container, keeps the same position. Both
	// ways: the list scrolls the header, and the header scrolls the list, because focusing a
	// resize handle that is partly off-screen makes the browser scroll the header to it.
	// Assigning an equal scrollLeft fires no scroll event, so the two cannot ping-pong.
	let header = $state<HTMLDivElement>();
	$effect(() => {
		const list = header?.nextElementSibling;
		if (!header || !(list instanceof HTMLElement)) return;
		const el = header;
		const fromList = () => {
			if (el.scrollLeft !== list.scrollLeft) el.scrollLeft = list.scrollLeft;
		};
		const fromHeader = () => {
			if (list.scrollLeft !== el.scrollLeft) list.scrollLeft = el.scrollLeft;
		};
		fromList();
		list.addEventListener('scroll', fromList, { passive: true });
		el.addEventListener('scroll', fromHeader, { passive: true });
		return () => {
			list.removeEventListener('scroll', fromList);
			el.removeEventListener('scroll', fromHeader);
		};
	});

	function widthOf(el: HTMLElement): number {
		return el.getBoundingClientRect().width;
	}

	function startDrag(e: PointerEvent, col: string) {
		const handle = e.currentTarget as HTMLElement;
		const cell = handle.parentElement as HTMLElement;
		const startX = e.clientX;
		const startW = widthOf(cell);
		handle.setPointerCapture(e.pointerId);
		const move = (ev: PointerEvent) =>
			libraryColumns.setWidth(col, startW + ev.clientX - startX, columnsView.ids);
		const end = () => {
			handle.removeEventListener('pointermove', move);
			handle.removeEventListener('pointerup', end);
			handle.removeEventListener('pointercancel', end);
			libraryColumns.persist();
		};
		handle.addEventListener('pointermove', move);
		handle.addEventListener('pointerup', end);
		handle.addEventListener('pointercancel', end);
		e.preventDefault();
	}

	function keyResize(e: KeyboardEvent, col: string) {
		if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
		const cell = (e.currentTarget as HTMLElement).parentElement as HTMLElement;
		libraryColumns.setWidth(col, widthOf(cell) + (e.key === 'ArrowRight' ? STEP : -STEP), columnsView.ids);
		libraryColumns.persist();
		e.preventDefault();
	}
</script>

<div class="ng-col-header" bind:this={header}>
	{#if librarySelection.on}<span class="check-spacer"></span>{/if}
	<div class="cells" style="grid-template-columns:{columnsView.template};min-width:{columnsView.minWidth}px">
		{#each columnsView.visible as col (col)}
			{@const def = columnsView.byId.get(col)}
			<span class="hcell" class:right={def?.align === 'right'} data-col={col}>
				<span class="label" title={def?.label()}>{col === 'swatch' ? '' : def?.label()}</span>
				<!-- The ARIA window-splitter pattern (tabindex, arrow keys, pointer drag), as upstream's
				     Splitter uses; Svelte's check does not know a separator can be interactive. -->
				<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
				<span
					class="handle"
					role="separator"
					aria-orientation="vertical"
					aria-label={ng.spool_columns_resize({ name: def?.label() ?? col })}
					aria-valuenow={Math.round(libraryColumns.config?.widths[col] ?? def?.width ?? 0)}
					tabindex="0"
					onpointerdown={(e) => startDrag(e, col)}
					onkeydown={(e) => keyResize(e, col)}
				></span>
			</span>
		{/each}
	</div>
</div>

<style>
	.ng-col-header {
		display: flex;
		border-top: 1px solid var(--border);
		background: var(--bg-subtle);
		/* Reserve the list's scrollbar width here too, or every fixed column would sit a
		   scrollbar's width to the right of the cells below it on systems that show one. */
		overflow: hidden;
		scrollbar-gutter: stable;
	}
	/* Only the list this header sits above: a bare `.groups` rule would reach upstream's list on
	   every install, since component styles load with the bundle, not with the component. */
	:global(.ng-col-header ~ .groups) {
		scrollbar-gutter: stable;
		overflow-x: auto;
	}
	.check-spacer {
		flex: none;
		width: 22px;
	}
	.cells {
		flex: 1;
		min-width: 0;
		display: grid;
		column-gap: 9px;
		padding: 5px 14px;
		border-left: 2px solid transparent;
	}
	.hcell {
		position: relative;
		min-width: 0;
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-dim);
		white-space: nowrap;
	}
	.hcell.right {
		text-align: right;
	}
	.label {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.hcell.right .label {
		padding-right: 4px;
	}
	/* Straddles the gap to the next column, so it is easy to grab without covering the label. */
	.handle {
		position: absolute;
		top: -5px;
		bottom: -5px;
		right: -7px;
		width: 6px;
		cursor: col-resize;
		touch-action: none;
		border-radius: 2px;
	}
	.handle:hover,
	.handle:focus-visible {
		background: var(--accent-border);
		outline: none;
	}
</style>
