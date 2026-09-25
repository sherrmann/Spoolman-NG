<script lang="ts">
	/**
	 * Spoolman NG fork addition (#412 step 5): choose, order and hide the flat list's columns.
	 *
	 * A checkbox per column and up/down buttons, so ordering works from the keyboard. Reset forgets
	 * the configuration, which brings back upstream's own row rather than a copy of it.
	 */
	import Columns from '@lucide/svelte/icons/columns-3';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { fields } from '$lib/stores/fields.svelte';
	import { libraryColumns } from '$lib/ng/libraryColumns.svelte';
	import { normaliseConfig, FLEX_COLUMN } from '$lib/ng/libraryColumns';
	import { columnsView } from '$lib/ng/libraryColumnsView.svelte';

	let open = $state(false);
	let trigger = $state<HTMLButtonElement>();
	let panel = $state<HTMLDivElement>();
	let order = $derived(normaliseConfig(libraryColumns.config, columnsView.ids).order);
	let shown = $derived(new Set(columnsView.visible));

	$effect(() => {
		if (open) fields.ensure('spool');
	});

	// Into the panel when it opens, and back to the button when it closes from inside, so a
	// keyboard user neither has to tab to it nor lands on the page body afterwards.
	$effect(() => {
		panel?.querySelector<HTMLElement>('input:not(:disabled), button:not(:disabled)')?.focus();
	});

	function onKey(e: KeyboardEvent) {
		if (open && e.key === 'Escape') close();
	}

	function close() {
		const within = panel?.contains(document.activeElement) ?? false;
		open = false;
		if (within) trigger?.focus();
	}
</script>

<!-- Escape is also handled on the button and the panel themselves: upstream's toolbar, which
     this sits in, stops keydown from reaching the window. -->
<svelte:window onkeydown={onKey} />

<div class="wrap">
	<button
		bind:this={trigger}
		class="trigger"
		class:active={open || columnsView.custom}
		aria-expanded={open}
		onkeydown={onKey}
		title={ng.buttons_columnsTooltip()}
		onclick={() => (open = !open)}
	>
		<Columns size={14} />
		{ng.buttons_columns()}
	</button>
	{#if open}
		<div
			class="panel"
			role="dialog"
			aria-label={ng.buttons_columns()}
			tabindex="-1"
			bind:this={panel}
			onkeydown={onKey}
		>
			<div class="head">
				<span class="title">{ng.buttons_columns()}</span>
				<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={14} /></button>
			</div>
			<ul>
				{#each order as id, i (id)}
					{@const def = columnsView.byId.get(id)}
					<li>
						<label>
							<input
								type="checkbox"
								checked={shown.has(id)}
								disabled={id === FLEX_COLUMN}
								onchange={() => libraryColumns.toggle(id, columnsView.ids)}
							/>
							{def?.label()}
						</label>
						<button
							class="move"
							disabled={i === 0}
							aria-label={ng.spool_columns_move_up({ name: def?.label() ?? id })}
							onclick={() => libraryColumns.move(id, -1, columnsView.ids)}><ArrowUp size={13} /></button
						>
						<button
							class="move"
							disabled={i === order.length - 1}
							aria-label={ng.spool_columns_move_down({ name: def?.label() ?? id })}
							onclick={() => libraryColumns.move(id, 1, columnsView.ids)}><ArrowDown size={13} /></button
						>
					</li>
				{/each}
			</ul>
			<button class="reset" disabled={!columnsView.custom} onclick={() => libraryColumns.reset()}>
				{ng.spool_columns_reset()}
			</button>
		</div>
	{/if}
</div>

<style>
	.wrap {
		position: relative;
		display: inline-flex;
	}
	/* The same look as the other fork controls in this row. */
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
	.panel {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		z-index: 30;
		width: 260px;
		max-width: 90vw;
		max-height: 60vh;
		overflow-y: auto;
		padding: 10px;
		background: var(--bg);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-md);
		box-shadow: 0 12px 36px rgba(0, 0, 0, 0.45);
	}
	.head {
		display: flex;
		align-items: center;
		margin-bottom: 6px;
	}
	.title {
		font-size: 12.5px;
		font-weight: 600;
	}
	.x {
		margin-left: auto;
		background: none;
		border: none;
		color: var(--text-dim);
		cursor: pointer;
		display: inline-flex;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 2px 0;
		font-size: 12.5px;
	}
	label {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
		cursor: pointer;
	}
	label input {
		margin: 0;
		accent-color: var(--accent);
	}
	.move {
		display: inline-flex;
		padding: 3px;
		background: none;
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		color: var(--text-dim);
		cursor: pointer;
	}
	.move:hover:not(:disabled) {
		border-color: var(--border);
		color: var(--text);
	}
	.move:disabled {
		opacity: 0.3;
		cursor: default;
	}
	.reset {
		margin-top: 8px;
		width: 100%;
		padding: 5px;
		font-size: 12px;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		color: var(--text-muted);
		cursor: pointer;
	}
	.reset:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
