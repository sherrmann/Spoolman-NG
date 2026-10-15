<script lang="ts">
	/**
	 * Scan-to-Spool photo intake (#361, #418) -- ported from the React client's
	 * `components/photoIntake.tsx` and the Photo tab of its scan modal.
	 *
	 * Three steps in one dialog: pick a photo, wait while the vision model reads it, then review
	 * what it read and choose what to do with it. "Continue" hands over to the ordinary Add-spools
	 * modal (see `ui.openAddModal`'s `intake` argument), which does the creating -- nothing is
	 * written to the server from here, and the photo itself is never stored on either end.
	 *
	 * Always mounted by the root layout and rendering nothing until `photoIntake.open`, so every
	 * use starts from a clean slate: the state below is reset by `close()` rather than by a
	 * remount.
	 */
	import Button from '$components/Button.svelte';
	import X from '@lucide/svelte/icons/x';
	import ImageIcon from '@lucide/svelte/icons/image';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { ui } from '$lib/stores/ui.svelte';
	import { spoolSource } from '$lib/api/spoolSource';
	import { isAbortError } from '$lib/api/http';
	import { photoIntake } from '$lib/ng/photoIntake.svelte';
	import {
		IntakeError,
		extractFromPhoto,
		extractionRows,
		handoffFor,
		intakeChoices,
		lookupCatalogueEntry,
		preparePhoto,
		rawDraftFrom,
		type IntakeChoice,
		type IntakeFailure,
		type RowKey,
		type SpoolIntakeResult
	} from '$lib/ng/spoolIntake';

	const THUMB_EDGE = 120;

	type Phase = 'pick' | 'extracting' | 'review';

	let phase = $state<Phase>('pick');
	let failure = $state<IntakeFailure | null>(null);
	let result = $state<SpoolIntakeResult | null>(null);
	let preview = $state<Blob | null>(null);
	let choice = $state('');
	let handingOver = $state(false);

	let dialog = $state<HTMLDivElement>();
	let fileInput = $state<HTMLInputElement>();
	let canvas = $state<HTMLCanvasElement>();
	let opener: HTMLElement | null = null;
	/** Aborted on close, so an answer that arrives for a dialog nobody is looking at is dropped. */
	let abort: AbortController | null = null;

	const rowLabel: Record<RowKey, () => string> = {
		vendor: ng.intake_fields_vendor,
		name: ng.intake_fields_name,
		material: ng.intake_fields_material,
		weight_g: ng.intake_fields_weight_g,
		diameter_mm: ng.intake_fields_diameter_mm,
		extruder_temp_c: ng.intake_fields_extruder_temp_c,
		bed_temp_c: ng.intake_fields_bed_temp_c,
		lot_nr: ng.intake_fields_lot_nr,
		article_number: ng.intake_fields_article_number,
		confidence: ng.intake_fields_confidence
	};

	const failureText: Record<IntakeFailure, () => string> = {
		disabled: ng.intake_errors_disabled,
		// The chat's wording already says what an administrator has to do about it.
		unconfigured: ng.chat_error_unconfigured,
		too_large: ng.intake_errors_too_large,
		bad_image: ng.intake_errors_bad_image,
		failed: ng.intake_errors_failed
	};

	const rows = $derived(result ? extractionRows(result.extraction) : []);
	const choices = $derived(result ? intakeChoices(result) : []);

	function choiceLabel(c: IntakeChoice): string {
		if (c.kind === 'raw') return ng.intake_use_raw();
		const where = c.kind === 'library' ? ng.intake_in_library() : ng.intake_from_catalog();
		return `${c.vendor ?? ''} ${c.name ?? ''} (${c.material ?? '?'}) - ${c.matchPercent}% - ${where}`;
	}

	$effect(() => {
		if (!photoIntake.open) return;
		opener = document.activeElement as HTMLElement | null;
		dialog?.focus();
		return () => opener?.focus();
	});

	/**
	 * The thumbnail is drawn onto a canvas rather than shown through an <img>: no string derived
	 * from the user-selected file ever reaches a DOM attribute, which is what CodeQL's
	 * js/xss-through-dom flags (it taints even URL.createObjectURL output via the File). Purely
	 * decorative -- it stays 0 x 0 when decoding fails, and the review works without it.
	 */
	$effect(() => {
		const target = canvas;
		const blob = preview;
		if (!target || !blob || phase !== 'review') return;
		let cancelled = false;
		(async () => {
			try {
				const bitmap = await createImageBitmap(blob);
				try {
					if (cancelled) return;
					const scale = Math.min(1, THUMB_EDGE / Math.max(bitmap.width, bitmap.height));
					target.width = Math.max(1, Math.round(bitmap.width * scale));
					target.height = Math.max(1, Math.round(bitmap.height * scale));
					target.getContext('2d')?.drawImage(bitmap, 0, 0, target.width, target.height);
				} finally {
					bitmap.close();
				}
			} catch {
				/* No preview, no problem. */
			}
		})();
		return () => {
			cancelled = true;
		};
	});

	function close() {
		abort?.abort();
		abort = null;
		phase = 'pick';
		failure = null;
		result = null;
		preview = null;
		choice = '';
		handingOver = false;
		photoIntake.close();
	}

	async function onFile(file: File) {
		failure = null;
		phase = 'extracting';
		abort?.abort();
		const controller = new AbortController();
		abort = controller;
		try {
			const photo = await preparePhoto(file);
			if (controller.signal.aborted) return;
			preview = photo.preview;
			const extracted = await extractFromPhoto(photo.base64, photo.mime, controller.signal);
			result = extracted;
			choice = intakeChoices(extracted)[0].value;
			phase = 'review';
		} catch (e) {
			if (isAbortError(e, controller.signal)) return;
			failure = e instanceof IntakeError ? e.failure : 'failed';
			phase = 'pick';
		}
	}

	/** Hand the choice to the Add-spools modal, falling back to the raw extraction. */
	async function proceed() {
		if (!result || handingOver) return;
		// The answer this handover is for. close() clears it and a new photo replaces it, so a
		// lookup that returns after either must not act on a session that has moved on.
		const session = result;
		const extraction = result.extraction;
		const handoff = handoffFor(choice, extraction);
		const fallback = { draft: rawDraftFrom(extraction) };
		handingOver = true;
		try {
			if (handoff.kind === 'library') {
				// The modal seeds itself from the inventory STORE, which only holds filaments that
				// have been listed; one with no spools yet is absent, and would open on the search
				// step as though nothing matched. fetchFilament upserts it, and answers undefined
				// for one deleted since the photo was read.
				const found = await spoolSource.fetchFilament(handoff.filamentId).catch(() => undefined);
				// Closed (or reopened on another photo) while the lookup ran: open nothing.
				if (!photoIntake.open || result !== session) return;
				close();
				if (found) ui.openAddModal(handoff.filamentId, handoff.lot ? { lot: handoff.lot } : null);
				else ui.openAddModal(undefined, fallback);
			} else if (handoff.kind === 'catalog') {
				// Looked up, not imported: the modal imports it on confirmation, so cancelling there
				// leaves the library untouched.
				const ext = await lookupCatalogueEntry(handoff.externalId);
				if (!photoIntake.open || result !== session) return;
				close();
				if (ext) ui.openAddModal(undefined, { external: ext, ...(handoff.lot ? { lot: handoff.lot } : {}) });
				else ui.openAddModal(undefined, fallback);
			} else {
				close();
				ui.openAddModal(undefined, { draft: handoff.draft });
			}
		} finally {
			handingOver = false;
		}
	}
</script>

<svelte:window onkeydown={(e) => photoIntake.open && e.key === 'Escape' && close()} />

{#if photoIntake.open}
	<div class="overlay">
		<!-- A sibling of the dialog rather than its parent, so interactive controls are not nested
		     inside an interactive element. -->
		<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={close}></button>
		<div
			class="modal"
			role="dialog"
			aria-modal="true"
			aria-labelledby="photo-intake-title"
			tabindex="-1"
			bind:this={dialog}
		>
			<div class="modal-head">
				<span class="title" id="photo-intake-title">{ng.intake_title()}</span>
				<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
			</div>

			<div class="body">
				{#if failure}
					<p class="note err" role="alert">{failureText[failure]()}</p>
				{/if}

				{#if phase === 'pick'}
					<div class="pick">
						<p class="note">{ng.intake_hint()}</p>
						<Button variant="primary" onclick={() => fileInput?.click()}>
							<ImageIcon size={14} />
							{ng.intake_select_photo()}
						</Button>
						<!-- `capture` asks a phone for its camera; a desktop browser shows a file picker. -->
						<input
							bind:this={fileInput}
							type="file"
							accept="image/*"
							capture="environment"
							hidden
							onchange={(e) => {
								const file = e.currentTarget.files?.[0];
								if (file) void onFile(file);
								e.currentTarget.value = '';
							}}
						/>
					</div>
				{:else if phase === 'extracting'}
					<div class="pick" role="status">
						<span class="spinner" aria-hidden="true"></span>
						<p class="note">{ng.intake_extracting()}</p>
					</div>
				{:else if result}
					<div class="review">
						<canvas bind:this={canvas} width="0" height="0" aria-hidden="true"></canvas>
						<dl>
							{#each rows as row (row.key)}
								<div>
									<dt>{rowLabel[row.key]()}</dt>
									<dd>{row.value}</dd>
								</div>
							{/each}
						</dl>
					</div>
					<fieldset class="choices">
						<legend>{ng.intake_choices_label()}</legend>
						{#each choices as c (c.value)}
							<label class="choice" class:selected={choice === c.value}>
								<input type="radio" name="intake-choice" value={c.value} bind:group={choice} />
								<span>{choiceLabel(c)}</span>
							</label>
						{/each}
					</fieldset>
					<p class="note dim">{ng.intake_photo_discarded()}</p>
				{/if}
			</div>

			<div class="foot">
				{#if phase === 'review'}
					<Button variant="outline" disabled={handingOver} onclick={() => (phase = 'pick')}
						>{ng.intake_back()}</Button
					>
					<Button variant="primary" disabled={handingOver || !choice} onclick={proceed}
						>{ng.intake_continue()}</Button
					>
				{:else}
					<Button variant="outline" onclick={close}>{m['buttons.cancel']()}</Button>
				{/if}
			</div>
		</div>
	</div>
{/if}

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
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 14px 20px 4px;
		overflow-y: auto;
	}
	.pick {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
		padding: 16px 0;
		text-align: center;
	}
	.note {
		margin: 0;
		font-size: 12.5px;
		line-height: 1.5;
		color: var(--text-muted);
	}
	.note.err {
		padding: 8px 10px;
		color: var(--danger);
		background: var(--danger-wash);
		border-radius: var(--radius-sm);
	}
	.note.dim {
		color: var(--text-dim);
	}
	.spinner {
		width: 22px;
		height: 22px;
		border: 2px solid var(--track);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation-duration: 3s;
		}
	}
	.review {
		display: flex;
		align-items: flex-start;
		gap: 14px;
	}
	canvas {
		flex: none;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border);
	}
	canvas[width='0'] {
		display: none;
	}
	dl {
		flex: 1;
		min-width: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	dl div {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		font-size: 12.5px;
	}
	dt {
		color: var(--text-muted);
	}
	dd {
		margin: 0;
		color: var(--text);
		text-align: right;
		overflow-wrap: anywhere;
	}
	.choices {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin: 0;
		padding: 0;
		border: none;
		min-width: 0;
	}
	.choices legend {
		padding: 0;
		margin-bottom: 6px;
		font-size: 12px;
		color: var(--text-muted);
	}
	.choice {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		padding: 7px 10px;
		font-size: 13px;
		line-height: 1.4;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		cursor: pointer;
	}
	.choice.selected {
		background: var(--accent-wash);
		border-color: var(--accent-border);
	}
	.choice input {
		margin-top: 2px;
		accent-color: var(--accent);
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px 16px;
		flex: none;
	}
</style>
