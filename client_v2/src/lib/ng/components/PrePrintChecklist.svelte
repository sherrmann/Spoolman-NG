<script lang="ts">
	// Pre-print checklist (#296) -- ported from
	// client/src/pages/printing/prePrintChecklistModal.tsx. The label preview is
	// geometrically exact, but the browser's print dialog can quietly re-scale the page,
	// pick a different paper, add driver margins or stamp headers and footers on it. This
	// names those four settings at the one moment they are about to be chosen: between the
	// panel's Print button and `window.print()`.
	//
	// The React original also carries a hint offering a one-click switch of its `pageSizeMode`
	// from "auto" to "label". This client has no such setting -- `$lib/labels/print` always
	// emits an explicit `@page { size: <W>mm <H>mm }` -- so there is nothing to fix and the
	// hint is dropped rather than replaced.
	//
	// The caller mounts this only while the checklist is actually open, the same way
	// MarkOrderedDialog is mounted, so `dontShowAgain` starts unticked on every opening with
	// nothing to reset.
	import Button from '$components/Button.svelte';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';

	interface Props {
		/** The page size the next print will ask the browser for, in mm. */
		paper: { w: number; h: number };
		onclose: () => void;
		onconfirm: (dontShowAgain: boolean) => void;
	}
	let { paper, onclose, onconfirm }: Props = $props();

	// Committed only on confirm, so cancelling never persists an accidental opt-out.
	let dontShowAgain = $state(false);

	let dialog = $state<HTMLDivElement>();
	let opener: HTMLElement | null = null;
	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		dialog?.focus();
		return () => opener?.focus();
	});

	// Paper sizes are millimetres and some of them are fractional (Letter is 215.9 mm), so
	// trim to a tenth rather than printing whatever the float maths produced.
	const mm = (n: number) => String(Math.round(n * 10) / 10);
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape') onclose();
	}}
/>

<div class="overlay">
	<!-- Click-outside catcher: a sibling of the dialog, not a parent, so it doesn't nest
	     interactive controls inside an interactive element. -->
	<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={onclose}></button>
	<div
		class="modal"
		role="dialog"
		aria-modal="true"
		aria-labelledby="pre-print-checklist-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="pre-print-checklist-title">{ng.printing_generic_checklist_title()}</span>
			<button class="x" onclick={onclose} aria-label={m['buttons.close']()}><X size={16} /></button>
		</div>

		<div class="body">
			<p class="intro">{ng.printing_generic_checklist_intro()}</p>
			<ul>
				<li>{ng.printing_generic_checklist_scale()}</li>
				<li>
					{ng.printing_generic_checklist_paperSize({ width: mm(paper.w), height: mm(paper.h) })}
				</li>
				<li>{ng.printing_generic_checklist_margins()}</li>
				<li>{ng.printing_generic_checklist_headersFooters()}</li>
			</ul>
		</div>

		<div class="foot">
			<label class="dont-show">
				<input type="checkbox" bind:checked={dontShowAgain} />
				{ng.printing_generic_checklist_dontShowAgain()}
			</label>
			<Button variant="outline" onclick={onclose}>{m['buttons.cancel']()}</Button>
			<Button variant="primary" onclick={() => onconfirm(dontShowAgain)}>
				{ng.printing_generic_checklist_printNow()}
			</Button>
		</div>
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
		width: 480px;
		max-width: 100%;
		max-height: 84vh;
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
		padding: 14px 20px 4px;
		overflow-y: auto;
		font-size: 13px;
	}
	.intro {
		margin: 0 0 10px;
		color: var(--text-dim);
		line-height: 1.5;
	}
	.body ul {
		margin: 0;
		padding-left: 20px;
		line-height: 1.6;
	}
	.foot {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px 16px;
		flex: none;
	}
	.dont-show {
		margin-right: auto;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 13px;
		color: var(--text-dim);
		cursor: pointer;
	}
</style>
