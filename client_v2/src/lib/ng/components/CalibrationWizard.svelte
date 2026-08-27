<script lang="ts">
	// Guided, multi-step calibration wizard (#123) -- ported from
	// client/src/pages/calibration/CalibrationWizard.tsx, minus its ~500 lines of flow-rate/PA/VFA
	// UI now shared with StepEditModal.svelte via StepEditor.svelte (see that file's own doc
	// comment). Walks WIZARD_STEP_ORDER: a clickable sidebar on the left (done marker, current
	// step highlighted, every step reachable), StepEditor plus confidence/notes on the right.
	//
	// Each step's `inputs`/`outputs` are kept as an in-memory draft per step type (`drafts`),
	// seeded once from the session's already-recorded steps and updated live as StepEditor calls
	// back -- Svelte's own reactivity is what would otherwise be React's per-navigation
	// `form.getFieldsValue()`/`setFieldsValue()` capture-and-restore dance (see
	// CalibrationWizard.tsx's `navigateTo`), so there is nothing to capture here: switching the
	// sidebar selection just points `currentStepType` at a different, already-live slice of
	// `drafts`.
	//
	// "Save & Continue"/"Save & Finish" POST/PATCH the current step immediately (addStep the
	// first time a type is recorded in this session, updateStep on every revisit) and only then
	// advance -- so Cancel never has to unwind anything: whatever was saved stayed saved, the
	// session stays `in_progress`, and reopening this same session resumes right where it left off.
	//
	// Skipping means two different things here, and they are kept apart deliberately:
	//
	//   Footer "Skip"  -- move on WITHOUT recording anything. The step stays unrecorded and can
	//                     be come back to; nothing is written. This is what the wizard's own
	//                     subtitle promises ("You can skip any step and resume later") and what
	//                     the finish confirmation says ("...without saving this step").
	//   Advisory skip  -- record the `_skipped` sentinel (see ../calibrationTypes), so the step
	//                     reads as "Skipped" from then on. Offered only where skipping is a
	//                     decision rather than a postponement: a printer that does input shaping
	//                     itself is never going to want that step.
	//
	// Collapsing the two -- making the footer button record the sentinel -- would leave a user
	// who clicked Skip meaning "later" with a step permanently marked as deliberately skipped,
	// undoable only by deleting the step result. Matches the React client, whose handleSkip
	// (CalibrationWizard.tsx:909) navigates and whose handleSaveAsSkipped writes the sentinel.
	import { untrack } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { STEP_CONFIGS, WIZARD_STEP_ORDER } from '../calibrationConfig';
	import {
		isSkipped,
		SKIPPED_SENTINEL,
		type CalibrationSession,
		type CalibrationStepResult
	} from '../calibrationTypes';
	import type { CalibrationStepType, StepBody } from '../calibrationTypes';
	import { addStep, updateStep, updateSession } from '../calibrationApi';
	import { stepCopyTitle, stepCopyDescription, stepWikiUrl } from '../calibrationLabels';
	import { ng } from '../i18n';
	import { HttpError } from '$lib/api/http';
	import { toasts } from '$lib/stores/toasts.svelte';
	import * as m from '$lib/paraglide/messages';
	import Button from '$components/Button.svelte';
	import ConfirmDialog from '$components/ConfirmDialog.svelte';
	import StepEditor from './StepEditor.svelte';
	import X from '@lucide/svelte/icons/x';
	import Check from '@lucide/svelte/icons/check';
	import BookOpen from '@lucide/svelte/icons/book-open';

	interface Props {
		session: CalibrationSession;
		/** Called after every persisted change (a step saved/skipped, or the session completed) --
		 *  the caller's cue to refresh its own session list. Does not close the modal by itself. */
		onsuccess: () => void;
		/** Close the modal. The session is left exactly as it was last saved -- see the module
		 *  doc comment on why Cancel never needs to undo anything. */
		onclose: () => void;
	}
	let { session, onsuccess, onclose }: Props = $props();

	interface StepDraft {
		inputs: Record<string, unknown>;
		outputs: Record<string, unknown>;
		confidence: string;
		notes: string;
	}
	function emptyDraft(): StepDraft {
		return { inputs: {}, outputs: {}, confidence: '', notes: '' };
	}
	/** A skipped step's sentinel outputs are not real field data -- start such a step blank. */
	function seedDraft(step: CalibrationStepResult | undefined): StepDraft {
		if (!step || isSkipped(step)) return emptyDraft();
		return {
			inputs: { ...(step.inputs ?? {}) },
			outputs: { ...(step.selectedValues ?? step.outputs ?? {}) },
			confidence: step.confidence ?? '',
			notes: step.notes ?? ''
		};
	}

	// This modal is only ever mounted while a wizard session is actually open (see the caller's
	// own `{#if wizardSession}`), so `session` never changes out from under it -- the same
	// once-only-seeding convention as OrderDetailsModal's `untrack(() => order)`.
	const initial = untrack(() => session);

	// SvelteSet, not a plain Set: it's mutated in place (persist() below just calls `.add`),
	// and SvelteSet is what makes that trigger the sidebar's own reactivity.
	let doneTypes = new SvelteSet<CalibrationStepType>(initial.steps.map((s) => s.stepType));
	let savedStepIds = $state<Partial<Record<CalibrationStepType, number>>>(
		Object.fromEntries(initial.steps.map((s) => [s.stepType, s.id])) as Partial<
			Record<CalibrationStepType, number>
		>
	);
	let drafts = $state<Record<CalibrationStepType, StepDraft>>(
		Object.fromEntries(
			WIZARD_STEP_ORDER.map((t) => [t, seedDraft(initial.steps.find((s) => s.stepType === t))])
		) as Record<CalibrationStepType, StepDraft>
	);

	const firstPending = WIZARD_STEP_ORDER.findIndex((t) => !doneTypes.has(t));
	let stepIndex = $state(firstPending >= 0 ? firstPending : 0);
	let submitting = $state(false);
	let confirmFinishOpen = $state(false);

	let currentStepType = $derived(WIZARD_STEP_ORDER[stepIndex]);
	let isFirst = $derived(stepIndex === 0);
	let isLast = $derived(stepIndex === WIZARD_STEP_ORDER.length - 1);
	let isCurrentDone = $derived(doneTypes.has(currentStepType));

	/**
	 * Move to a step. Unguarded on purpose.
	 *
	 * This used to refuse while `submitting` was true, which looked like a sensible "don't
	 * navigate mid-save" rule and was in fact a bug: saveAndContinue() sets `submitting`,
	 * awaits the write, and THEN calls this to advance -- all before its `finally` clears the
	 * flag. So every Save & Continue persisted the step and then silently stayed put. (Skip
	 * appeared to work only because it never sets the flag.)
	 *
	 * The rule the guard was reaching for is about the USER, not about this function, so it
	 * now lives on the sidebar buttons that the user can click -- the only way to jump steps
	 * while a write is in flight.
	 */
	function navigateTo(idx: number) {
		stepIndex = idx;
	}

	function reportError(e: unknown, context: string) {
		console.error(context, e);
		toasts.error(m['notifications.error']({ statusCode: e instanceof HttpError ? e.status : '?' }));
	}

	/** The subset of `outputs` named by the step's recommendedKeys -- the "recommended settings". */
	function selectedValuesOf(
		type: CalibrationStepType,
		outputs: Record<string, unknown>
	): Record<string, unknown> {
		const selected: Record<string, unknown> = {};
		for (const key of STEP_CONFIGS[type].recommendedKeys) {
			if (outputs[key] !== undefined && outputs[key] !== null) selected[key] = outputs[key];
		}
		return selected;
	}

	function bodyFor(type: CalibrationStepType, draft: StepDraft, skip: boolean): StepBody {
		if (skip) {
			return {
				step_type: type,
				inputs: null,
				outputs: { [SKIPPED_SENTINEL]: true },
				selected_values: null,
				notes: null,
				confidence: null
			};
		}
		const selected = selectedValuesOf(type, draft.outputs);
		return {
			step_type: type,
			inputs: Object.keys(draft.inputs).length > 0 ? draft.inputs : null,
			outputs: Object.keys(draft.outputs).length > 0 ? draft.outputs : null,
			selected_values: Object.keys(selected).length > 0 ? selected : null,
			notes: draft.notes.trim() ? draft.notes.trim() : null,
			confidence: draft.confidence || null
		};
	}

	async function persist(type: CalibrationStepType, body: StepBody): Promise<void> {
		const existingId = savedStepIds[type];
		const result = existingId != null ? await updateStep(existingId, body) : await addStep(session.id, body);
		savedStepIds = { ...savedStepIds, [type]: result.id };
		doneTypes.add(type);
	}

	async function finish(): Promise<void> {
		await updateSession(session.id, { status: 'complete' });
		onsuccess();
		onclose();
	}

	async function saveAndContinue() {
		if (submitting) return;
		submitting = true;
		try {
			await persist(currentStepType, bodyFor(currentStepType, drafts[currentStepType], false));
			onsuccess();
			if (isLast) await finish();
			else navigateTo(stepIndex + 1);
		} catch (e) {
			reportError(e, 'Failed to save calibration step');
		} finally {
			submitting = false;
		}
	}

	/** Move on without recording. See the note at the top on why this writes nothing. */
	function handleSkip() {
		if (submitting) return;
		if (isLast) {
			confirmFinishOpen = true;
			return;
		}
		navigateTo(stepIndex + 1);
	}

	/** Record this step as deliberately skipped, then advance (or finish on the last step). */
	async function markSkipped() {
		if (submitting) return;
		submitting = true;
		try {
			await persist(currentStepType, bodyFor(currentStepType, drafts[currentStepType], true));
			onsuccess();
			if (isLast) await finish();
			else navigateTo(stepIndex + 1);
		} catch (e) {
			reportError(e, 'Failed to skip calibration step');
		} finally {
			submitting = false;
		}
	}

	/**
	 * "Mark this session as complete without saving this step?" -- so it saves nothing, which is
	 * exactly what that confirmation promises. Writing the skip sentinel here would record a
	 * decision the user was never asked to make.
	 */
	async function confirmSkipAndFinish() {
		submitting = true;
		try {
			await finish();
		} catch (e) {
			reportError(e, 'Failed to finish calibration session');
		} finally {
			submitting = false;
			confirmFinishOpen = false;
		}
	}

	function cancel() {
		if (!submitting) onclose();
	}

	let dialog = $state<HTMLDivElement>();
	let opener: HTMLElement | null = null;
	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		dialog?.focus();
		return () => opener?.focus();
	});
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape' && !confirmFinishOpen) cancel();
	}}
/>

<div class="overlay">
	<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={cancel}></button>
	<div
		class="modal"
		role="dialog"
		aria-modal="true"
		aria-labelledby="calibration-wizard-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="calibration-wizard-title">{ng.calibration_wizard_title()}</span>
			{#if isCurrentDone}<span class="revisiting-tag">{ng.calibration_wizard_revisiting()}</span>{/if}
			<span class="step-count">
				{ng.calibration_wizard_step_of({ current: stepIndex + 1, total: WIZARD_STEP_ORDER.length })}
			</span>
			<button class="x" onclick={cancel} aria-label={m['buttons.close']()}><X size={16} /></button>
		</div>

		<div class="body">
			<nav class="sidebar" aria-label={ng.calibration_wizard_title()}>
				{#each WIZARD_STEP_ORDER as stepType, idx (stepType)}
					{@const isCurrent = idx === stepIndex}
					{@const isDone = doneTypes.has(stepType)}
					<button
						type="button"
						class="side-item"
						class:current={isCurrent}
						aria-current={isCurrent ? 'step' : undefined}
						disabled={submitting}
						onclick={() => navigateTo(idx)}
					>
						<span class="side-dot" class:done={isDone && !isCurrent}>
							{#if isDone && !isCurrent}<Check size={11} />{:else}{idx + 1}{/if}
						</span>
						<span class="side-label">{stepCopyTitle(stepType)}</span>
					</button>
				{/each}
			</nav>

			<div class="content">
				<div class="content-head">
					<h2>{stepCopyTitle(currentStepType)}</h2>
					<!-- stepWikiUrl() always returns an absolute github.com URL; there is no deploy
					     base path to resolve it against, same reasoning as EditableField.svelte's own
					     external link. -->
					<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
					<a class="wiki-link" href={stepWikiUrl(currentStepType)} target="_blank" rel="noopener noreferrer">
						<BookOpen size={12} />
						{ng.calibration_wiki_link()}
					</a>
				</div>
				<p class="description">{stepCopyDescription(currentStepType)}</p>

				<StepEditor
					stepType={currentStepType}
					inputs={drafts[currentStepType].inputs}
					outputs={drafts[currentStepType].outputs}
					variant="wizard"
					onchange={(next) => {
						drafts[currentStepType] = {
							...drafts[currentStepType],
							inputs: next.inputs,
							outputs: next.outputs
						};
					}}
					onmarkskipped={markSkipped}
				/>

				<div class="meta-row">
					<label class="meta-field">
						<span>{ng.calibration_fields_confidence()}</span>
						<select
							class="sel"
							bind:value={drafts[currentStepType].confidence}
							aria-label={ng.calibration_fields_confidence()}
						>
							<option value="">{ng.calibration_optional()}</option>
							<option value="high">{ng.calibration_confidence_high()}</option>
							<option value="medium">{ng.calibration_confidence_medium()}</option>
							<option value="low">{ng.calibration_confidence_low()}</option>
						</select>
					</label>
					<label class="meta-field notes">
						<span>{ng.calibration_fields_notes()}</span>
						<textarea
							class="notes-input"
							rows="2"
							placeholder={ng.calibration_optional_notes()}
							bind:value={drafts[currentStepType].notes}></textarea>
					</label>
				</div>
			</div>
		</div>

		<div class="foot">
			<Button variant="ghost" disabled={submitting} onclick={cancel}
				>{ng.calibration_wizard_buttons_cancel()}</Button
			>
			<span class="spacer"></span>
			<Button variant="outline" disabled={isFirst || submitting} onclick={() => navigateTo(stepIndex - 1)}>
				{ng.calibration_wizard_buttons_back()}
			</Button>
			<Button variant="outline" disabled={submitting} onclick={handleSkip}>
				{isLast ? ng.calibration_wizard_buttons_skip_finish() : ng.calibration_wizard_buttons_skip()}
			</Button>
			<Button variant="primary" disabled={submitting} onclick={saveAndContinue}>
				{isLast ? ng.calibration_wizard_buttons_save_finish() : ng.calibration_wizard_buttons_save_continue()}
			</Button>
		</div>
	</div>
</div>

<ConfirmDialog
	open={confirmFinishOpen}
	busy={submitting}
	title={ng.calibration_wizard_title()}
	lines={[ng.calibration_wizard_skip_finish_confirm()]}
	confirmLabel={ng.calibration_wizard_buttons_finish()}
	onconfirm={confirmSkipAndFinish}
	onclose={() => (confirmFinishOpen = false)}
/>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		z-index: 60;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding: 5vh 16px 16px;
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
		width: 900px;
		max-width: 100%;
		max-height: 90vh;
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
		padding: 16px 20px;
		flex: none;
		border-bottom: 1px solid var(--border-soft);
	}
	.title {
		font-weight: 700;
		font-size: 15px;
	}
	.revisiting-tag {
		font-size: 11px;
		font-weight: 700;
		padding: 2px 8px;
		border-radius: 999px;
		background: var(--accent-wash);
		color: var(--accent-soft);
	}
	.step-count {
		margin-left: auto;
		font-size: 12.5px;
		color: var(--text-dim);
	}
	.x {
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
		flex: 1;
		min-height: 0;
		display: flex;
		overflow: hidden;
	}
	.sidebar {
		width: 200px;
		flex: none;
		padding: 10px;
		overflow-y: auto;
		border-right: 1px solid var(--border-soft);
		background: var(--surface);
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.side-item {
		display: flex;
		align-items: center;
		gap: 8px;
		height: 34px;
		padding: 0 8px;
		border-radius: var(--radius);
		border: none;
		background: none;
		cursor: pointer;
		text-align: left;
	}
	.side-item:hover {
		background: var(--surface-raised);
	}
	.side-item.current {
		background: var(--accent-wash);
	}
	.side-dot {
		flex: none;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font-size: 11px;
		font-weight: 700;
		background: var(--surface-raised);
		color: var(--text-faint);
	}
	.side-item.current .side-dot {
		background: var(--accent-fill);
		color: #fff;
	}
	.side-dot.done {
		background: var(--success-wash, rgba(74, 158, 110, 0.16));
		color: var(--success);
	}
	.side-label {
		font-size: 13px;
		color: var(--text-2);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.side-item.current .side-label {
		font-weight: 600;
		color: var(--accent-soft);
	}

	.content {
		flex: 1;
		min-width: 0;
		padding: 20px 24px;
		overflow-y: auto;
	}
	.content-head {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.content-head h2 {
		margin: 0;
		font-size: 17px;
		font-weight: 700;
	}
	.wiki-link {
		margin-left: auto;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 11.5px;
		color: var(--text-faint);
		text-decoration: none;
		padding: 3px 8px;
		border-radius: var(--radius);
		border: 1px solid var(--border);
		flex: none;
	}
	.wiki-link:hover {
		color: var(--accent-soft);
		border-color: var(--accent-soft);
	}
	.description {
		margin: 6px 0 18px;
		font-size: 13px;
		line-height: 1.55;
		color: var(--text-dim);
	}

	.meta-row {
		display: flex;
		gap: 16px;
		margin-top: 16px;
		flex-wrap: wrap;
	}
	.meta-field {
		display: flex;
		flex-direction: column;
		gap: 5px;
		font-size: 12px;
		color: var(--text-2);
		flex: 1 1 160px;
	}
	.meta-field.notes {
		flex: 2 1 260px;
	}
	.sel {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 7px 8px;
		font-size: 13px;
	}
	.notes-input {
		width: 100%;
		border: 1px solid var(--border-strong);
		background: none;
		border-radius: 7px;
		padding: 8px 10px;
		color: var(--text);
		font-size: 13px;
		font-family: inherit;
		resize: vertical;
	}
	.notes-input:focus {
		outline: none;
		border-color: var(--accent);
	}

	.foot {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 14px 20px;
		flex: none;
		border-top: 1px solid var(--border-soft);
	}
	.spacer {
		flex: 1;
	}
</style>
