<script lang="ts">
	// Low-stock-threshold editor for a Low Stock row (#298 redesign) — ported from
	// client/src/pages/lowstock/thresholdEdit.tsx. A button showing the current threshold
	// ("Threshold: 500 g") or, for a row only caught by the global fallback, the bare
	// "Adjust threshold" label opens a small popover with a gram input. Shared by the full
	// Low Stock page and the dashboard's Low Stock tab, so both stay consistent.
	//
	// Unlike the antd Popover it replaces, there is no separate "invalidate the list" step:
	// the write goes straight through trackSave (the same fire-and-forget wrapper every
	// other inline-editing field in this app uses), and `onSaved` tells the caller to
	// re-fetch the real server value — win or lose — rather than this popover guessing at
	// what landed.
	import { portal } from '$lib/actions/portal';
	import { numericInput, parseDecimal } from '$lib/utils/numeric';
	import { setLowStockThreshold } from '$lib/ng/api';
	import { trackSave } from '$lib/utils/autosave';
	import { weightAuto } from '$lib/utils/format';
	import { ng } from '$lib/ng/i18n';

	interface Props {
		filamentId: string;
		value: number | undefined;
		/** Called once the write settles (success or failure). */
		onSaved: () => void;
	}
	let { filamentId, value, onSaved }: Props = $props();

	let open = $state(false);
	let draft = $state('');
	let btn = $state<HTMLButtonElement>();
	let inputEl = $state<HTMLInputElement>();
	let popStyle = $state('');
	// Set by discard() right before it closes the popover, so the blur that removing a
	// focused node from the DOM triggers doesn't also fire a redundant commit() below.
	let suppressBlur = false;

	const label = $derived(
		value != null
			? ng.low_stock_threshold_button_value({ value: weightAuto(value) })
			: ng.low_stock_threshold_button()
	);

	function position() {
		if (!btn) return;
		const r = btn.getBoundingClientRect();
		popStyle = `top:${r.bottom + 4}px; left:${Math.max(8, r.right - 120)}px;`;
	}

	function openPopover() {
		draft = value != null ? String(value) : '';
		position();
		open = true;
		// The input doesn't exist until the {#if open} block below renders it.
		queueMicrotask(() => inputEl?.focus());
	}

	/** Save the draft (blank clears the threshold back to the global fallback) and close. */
	async function commit() {
		const t = draft.trim();
		const grams = t === '' ? null : parseDecimal(t);
		open = false;
		await trackSave(setLowStockThreshold(filamentId, grams), 'Low stock threshold save failed');
		onSaved();
	}

	/** Close without saving -- the popover's only way to abandon an edit. */
	function discard() {
		suppressBlur = true;
		open = false;
	}

	function onBlur() {
		if (suppressBlur) {
			suppressBlur = false;
			return;
		}
		commit();
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			commit();
		} else if (e.key === 'Escape') {
			// stopPropagation so an enclosing dialog's own Escape handler (the row this sits
			// in is not one today, but a future caller might be) doesn't also close on it.
			e.stopPropagation();
			discard();
		}
	}

	$effect(() => {
		if (!open) return;
		window.addEventListener('scroll', position, true);
		window.addEventListener('resize', position);
		return () => {
			window.removeEventListener('scroll', position, true);
			window.removeEventListener('resize', position);
		};
	});
</script>

<button
	type="button"
	class="threshold-btn"
	bind:this={btn}
	onclick={(e) => {
		e.stopPropagation();
		if (open) commit();
		else openPopover();
	}}
>
	{label}
</button>

{#if open}
	<div
		class="threshold-pop"
		use:portal
		style={popStyle}
		role="dialog"
		aria-modal="false"
		aria-label={ng.low_stock_threshold_button()}
	>
		<input
			bind:this={inputEl}
			class="mono"
			type="text"
			inputmode="decimal"
			use:numericInput={{ negative: false }}
			value={draft}
			oninput={(e) => (draft = e.currentTarget.value)}
			onkeydown={onKeydown}
			onblur={onBlur}
			aria-label={ng.low_stock_threshold_button()}
		/>
		<span class="unit">g</span>
	</div>
{/if}

<style>
	.threshold-btn {
		display: inline-flex;
		align-items: center;
		white-space: nowrap;
		border: 1px solid var(--border-strong);
		background: none;
		color: var(--text-2);
		border-radius: var(--radius);
		padding: 6px 10px;
		font-size: 12px;
		font-weight: 500;
		font-family: inherit;
		cursor: pointer;
	}
	.threshold-btn:hover {
		border-color: var(--accent);
		color: var(--text);
	}

	.threshold-pop {
		position: fixed;
		z-index: 100;
		display: flex;
		align-items: center;
		gap: 4px;
		background: var(--surface-raised);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-md);
		box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
		padding: 6px 8px;
	}
	.threshold-pop input {
		width: 70px;
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 5px 7px;
		font-size: 13px;
	}
	.threshold-pop input:focus {
		outline: none;
		border-color: var(--accent);
	}
	.threshold-pop .unit {
		color: var(--text-muted);
		font-size: 12px;
	}
</style>
