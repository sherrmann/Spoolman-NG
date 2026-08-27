<script lang="ts">
	/**
	 * A small confirm dialog for the scanner's two questions: move this spool here, and create a
	 * filament for this unrecognised barcode.
	 *
	 * Not upstream's ConfirmDialog, deliberately. That one is documented as being for
	 * DESTRUCTIVE actions and styles its confirm button `danger`; both questions here are
	 * routine, and a red button on "Move spool" tells the user something is about to be lost.
	 * Its title element also carries a hardcoded id, which two of them on one page would
	 * duplicate. The chrome below is otherwise the same shape as its, on purpose -- these should
	 * not look like a different application.
	 */
	import Button from '$lib/components/Button.svelte';
	import * as m from '$lib/paraglide/messages';
	import X from '@lucide/svelte/icons/x';

	interface Props {
		title: string;
		/** What is about to happen, spelled out -- one paragraph per entry. */
		lines: string[];
		confirmLabel: string;
		onconfirm: () => void;
		onclose: () => void;
		/** Disables both buttons while the request is in flight. */
		busy?: boolean;
	}
	let { title, lines, confirmLabel, onconfirm, onclose, busy = false }: Props = $props();

	let dialog = $state<HTMLDivElement | null>(null);
	// Captured before the dialog takes focus and restored on unmount, so dismissing puts the
	// user back where they were -- which here is the scanner, still running behind this.
	let opener: HTMLElement | null = null;
	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		dialog?.focus();
		return () => opener?.focus();
	});

	function close() {
		if (!busy) onclose();
	}
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && close()} />

<div class="overlay">
	<!-- A sibling of the dialog rather than its parent, so interactive controls are not nested
	     inside an interactive element. Escape is handled on the window above. -->
	<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={close}></button>
	<div class="dialog" role="dialog" aria-modal="true" aria-label={title} tabindex="-1" bind:this={dialog}>
		<div class="head">
			<span class="title">{title}</span>
			<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
		</div>
		<div class="body">
			{#each lines as line (line)}
				<p>{line}</p>
			{/each}
		</div>
		<div class="foot">
			<Button variant="outline" disabled={busy} onclick={close}>{m['buttons.cancel']()}</Button>
			<Button variant="primary" disabled={busy} onclick={onconfirm}>{confirmLabel}</Button>
		</div>
	</div>
</div>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		/* Above the scanner modal's own overlay (z-index 50), which stays open behind this. */
		z-index: 60;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding: 12vh 16px 16px;
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
	.dialog {
		position: relative;
		z-index: 1;
		width: 420px;
		max-width: 100%;
		background: var(--bg);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-xl);
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
		overflow: hidden;
	}
	.head {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 16px 20px 0;
	}
	.title {
		font-weight: 700;
		font-size: 15px;
	}
	.x {
		margin-left: auto;
		display: inline-flex;
		color: var(--text-dim);
		cursor: pointer;
		padding: 4px 8px;
		background: none;
		border: none;
	}
	.x:hover {
		color: var(--text);
	}
	.body {
		padding: 12px 20px 4px;
		font-size: 13px;
		line-height: 1.5;
		color: var(--text-2);
	}
	.body p {
		margin: 0 0 8px;
	}
	.body p:last-child {
		margin-bottom: 0;
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 16px 20px 18px;
	}
</style>
