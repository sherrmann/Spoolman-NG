<script lang="ts">
	// Add/edit a single calibration step outside the guided wizard (#123) -- ported from
	// client/src/pages/calibration/StepResultDrawer.tsx, but sharing StepEditor.svelte with
	// CalibrationWizard.svelte instead of re-implementing its flow-rate/PA/VFA UI a second time.
	//
	// Mounted only while actually open (`{#if editingStep}<StepEditModal .../>{/if}`), same
	// conditionally-mounted convention as OrderDetailsModal -- so every `$state` below is seeded
	// once, from the step (if any) this opened with.
	import { untrack } from 'svelte';
	import { WIZARD_STEP_ORDER, STEP_CONFIGS } from '../calibrationConfig';
	import {
		isSkipped,
		type CalibrationStepResult,
		type CalibrationStepType,
		type StepBody
	} from '../calibrationTypes';
	import { addStep, updateStep } from '../calibrationApi';
	import { stepTypeLabel } from '../calibrationLabels';
	import { ng } from '../i18n';
	import { HttpError } from '$lib/api/http';
	import { toasts } from '$lib/stores/toasts.svelte';
	import * as m from '$lib/paraglide/messages';
	import Button from '$components/Button.svelte';
	import Field from '$components/Field.svelte';
	import FieldGrid from '$components/FieldGrid.svelte';
	import StepEditor from './StepEditor.svelte';
	import X from '@lucide/svelte/icons/x';

	interface Props {
		sessionId: number;
		/** Present when editing an already-recorded step; absent when adding a new one. */
		step?: CalibrationStepResult;
		onclose: () => void;
		onsuccess: () => void;
	}
	let { sessionId, step, onclose, onsuccess }: Props = $props();

	const initial = untrack(() => step);
	const isEditing = initial !== undefined;

	let stepType = $state<CalibrationStepType>(initial?.stepType ?? WIZARD_STEP_ORDER[0]);
	// A skipped step's sentinel outputs are not real field data -- start such a step blank,
	// same as CalibrationWizard's own seedDraft.
	let inputs = $state<Record<string, unknown>>(
		initial && !isSkipped(initial) ? { ...(initial.inputs ?? {}) } : {}
	);
	let outputs = $state<Record<string, unknown>>(
		initial && !isSkipped(initial) ? { ...(initial.selectedValues ?? initial.outputs ?? {}) } : {}
	);
	let confidence = $state(initial?.confidence ?? '');
	let notes = $state(initial?.notes ?? '');
	let submitting = $state(false);

	/** Only reachable while creating -- the type <select> is disabled once editing. Different
	 *  step types have different fields, so switching type starts both blank. */
	function changeStepType(next: CalibrationStepType) {
		stepType = next;
		inputs = {};
		outputs = {};
	}

	let dialog = $state<HTMLDivElement>();
	let opener: HTMLElement | null = null;
	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		dialog?.focus();
		return () => opener?.focus();
	});

	function close() {
		if (!submitting) onclose();
	}

	async function submit() {
		if (submitting) return;
		submitting = true;
		try {
			const cfg = STEP_CONFIGS[stepType];
			const selected: Record<string, unknown> = {};
			for (const key of cfg.recommendedKeys) {
				if (outputs[key] !== undefined && outputs[key] !== null) selected[key] = outputs[key];
			}
			const body: StepBody = {
				step_type: stepType,
				inputs: Object.keys(inputs).length > 0 ? inputs : null,
				outputs: Object.keys(outputs).length > 0 ? outputs : null,
				selected_values: Object.keys(selected).length > 0 ? selected : null,
				notes: notes.trim() ? notes.trim() : null,
				confidence: confidence || null
			};
			if (isEditing && initial) await updateStep(initial.id, body);
			else await addStep(sessionId, body);
			onsuccess();
			onclose();
		} catch (e) {
			console.error('Failed to save calibration step', e);
			toasts.error(m['notifications.error']({ statusCode: e instanceof HttpError ? e.status : '?' }));
		} finally {
			submitting = false;
		}
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
		aria-labelledby="step-edit-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="step-edit-title">
				{isEditing ? ng.calibration_step_form_edit_title() : ng.calibration_step_form_add_title()}
			</span>
			<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
		</div>

		<form
			class="body"
			onsubmit={(e) => {
				e.preventDefault();
				submit();
			}}
		>
			<FieldGrid labelWidth="140px">
				<Field label={ng.calibration_fields_step_type()}>
					<select
						class="sel"
						value={stepType}
						disabled={isEditing}
						aria-label={ng.calibration_fields_step_type()}
						onchange={(e) => changeStepType(e.currentTarget.value as CalibrationStepType)}
					>
						{#each WIZARD_STEP_ORDER as t (t)}
							<option value={t}>{stepTypeLabel(t)}</option>
						{/each}
					</select>
				</Field>
			</FieldGrid>

			<div class="editor-wrap">
				<StepEditor
					{stepType}
					{inputs}
					{outputs}
					variant="drawer"
					onchange={(next) => {
						inputs = next.inputs;
						outputs = next.outputs;
					}}
				/>
			</div>

			<FieldGrid labelWidth="140px">
				<Field label={ng.calibration_fields_confidence()}>
					<select class="sel" bind:value={confidence} aria-label={ng.calibration_fields_confidence()}>
						<option value="">{ng.calibration_optional()}</option>
						<option value="high">{ng.calibration_confidence_high()}</option>
						<option value="medium">{ng.calibration_confidence_medium()}</option>
						<option value="low">{ng.calibration_confidence_low()}</option>
					</select>
				</Field>
				<Field label={ng.calibration_fields_notes()}>
					<textarea class="comment" rows="2" placeholder={ng.calibration_optional_notes()} bind:value={notes}
					></textarea>
				</Field>
			</FieldGrid>
		</form>

		<div class="foot">
			<Button variant="outline" disabled={submitting} onclick={close}>{m['buttons.cancel']()}</Button>
			<Button variant="primary" disabled={submitting} onclick={submit}>{ng.calibration_buttons_save()}</Button
			>
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
		padding: 6vh 16px 16px;
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
		width: 620px;
		max-width: 100%;
		max-height: 88vh;
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
	}
	.editor-wrap {
		margin: 16px 0;
	}
	.sel {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 8px 8px;
		font-size: 13px;
		width: 100%;
	}
	.comment {
		width: 100%;
		border: 1px solid var(--border-strong);
		background: none;
		border-radius: 7px;
		padding: 9px 12px;
		color: var(--text);
		font-size: 13px;
		font-family: inherit;
		resize: vertical;
	}
	.comment:focus {
		outline: none;
		border-color: var(--accent);
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px 16px;
		flex: none;
	}
</style>
