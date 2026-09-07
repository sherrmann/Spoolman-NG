<script lang="ts">
	/**
	 * The dialog shell shared by this fork's small edit forms (printer, link, password).
	 *
	 * Upstream's ConfirmDialog is documented as being for destructive actions and takes plain
	 * text, not a form; NewLocationModal is this same shell written out for one field. Three more
	 * copies of the overlay, the focus handling and the styles would be three places to fix the
	 * next accessibility finding, so the shell is lifted out here and the forms fill it in.
	 *
	 * The caller owns the form and its state, and writes its fields with the `fld`/`lbl`/`in`/
	 * `error` classes styled at the bottom of this file. Pressing Enter inside submits through the form
	 * element's own `onsubmit`, so `onsubmit` is wired here rather than on a button.
	 */
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		/** Disables closing while a request is in flight; the buttons are the caller's. */
		busy?: boolean;
		onclose: () => void;
		onsubmit: () => void;
		children: Snippet;
		footer: Snippet;
	}
	let { title, busy = false, onclose, onsubmit, children, footer }: Props = $props();

	const titleId = $props.id();
	let dialog = $state<HTMLDivElement>();
	let opener: HTMLElement | null = null;
	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		// Focus the first field rather than the dialog itself, so typing can start at once.
		const first = dialog?.querySelector<HTMLElement>('input, select, textarea');
		(first ?? dialog)?.focus();
		return () => opener?.focus();
	});

	function close() {
		if (!busy) onclose();
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape') close();
	}}
/>

<div class="overlay">
	<!-- Click-outside catcher: a sibling of the dialog, not a parent, so it doesn't nest
	     interactive controls inside an interactive element. -->
	<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={close}></button>
	<div
		class="modal"
		role="dialog"
		aria-modal="true"
		aria-labelledby={titleId}
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id={titleId}>{title}</span>
			<button type="button" class="x" onclick={close} aria-label={m['buttons.close']()}
				><X size={16} /></button
			>
		</div>
		<form
			class="body"
			onsubmit={(e) => {
				e.preventDefault();
				if (!busy) onsubmit();
			}}
		>
			{@render children()}
			<div class="foot">{@render footer()}</div>
		</form>
	</div>
</div>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		z-index: 60;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding: 8vh 16px 16px;
	}
	.backdrop {
		position: fixed;
		inset: 0;
		border: none;
		margin: 0;
		padding: 0;
		background: transparent;
		cursor: default;
	}
	.modal {
		position: relative;
		z-index: 1;
		width: 420px;
		max-width: 100%;
		display: flex;
		flex-direction: column;
		background: var(--bg);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-xl);
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
		overflow: hidden;
	}
	.modal-head {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 16px 20px 0;
		flex: none;
	}
	.title {
		font-weight: 700;
		font-size: 15px;
	}
	.x {
		margin-left: auto;
		color: var(--text-dim);
		cursor: pointer;
		padding: 4px 8px;
		background: none;
		border: none;
		display: inline-flex;
	}
	.x:hover {
		color: var(--text);
	}
	.body {
		padding: 16px 20px 0;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 6px 0 16px;
		flex: none;
	}
	/* The fields are the caller's markup, so their rules live here under :global rather than
	   being copied into every form. */
	.body :global(.fld) {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.body :global(.lbl),
	.body :global(.hint),
	.body :global(.help) {
		font-size: 12px;
		color: var(--text-muted);
		margin: 0;
	}
	.body :global(.in) {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 7px 10px;
		font-size: 13px;
		font-family: inherit;
	}
	.body :global(.in:focus) {
		border-color: var(--accent);
	}
	.body :global(.in.invalid) {
		border-color: var(--danger);
	}
	.body :global(.error) {
		color: var(--danger-soft);
		font-size: 12px;
	}
</style>
