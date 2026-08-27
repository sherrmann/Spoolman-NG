<script lang="ts">
	// Calibration session metadata form (#123) -- ported from
	// client/src/pages/calibration/SessionFormModal.tsx, trimmed to this fork's own scope: printer
	// name, nozzle diameter and notes. (The React original also exposed a `status` select; the
	// route here drives status itself -- 'in_progress' on create via the wizard, 'complete' when
	// the wizard finishes -- so a free-standing status editor is left out rather than offering a
	// second way to get a session into a state the wizard's own flow wouldn't produce.)
	//
	// One component for both create and edit, chosen by `mode`, matching the React original's own
	// split. `filamentId` is required for `mode="create"`; `session` is required for `mode="edit"`.
	//
	// Mounted only while actually open, same conditionally-mounted convention as OrderDetailsModal
	// -- so every `$state` below is seeded once, from `session` (in edit mode) this opened with.
	import { untrack } from 'svelte';
	import { createSession, updateSession } from '../calibrationApi';
	import type { CalibrationSession, SessionBody } from '../calibrationTypes';
	import { ng } from '../i18n';
	import { HttpError } from '$lib/api/http';
	import { parseDecimal } from '$lib/utils/numeric';
	import { toasts } from '$lib/stores/toasts.svelte';
	import * as m from '$lib/paraglide/messages';
	import Button from '$components/Button.svelte';
	import Field from '$components/Field.svelte';
	import FieldGrid from '$components/FieldGrid.svelte';
	import EditableField from '$components/EditableField.svelte';
	import NumberInput from '$components/NumberInput.svelte';
	import X from '@lucide/svelte/icons/x';

	interface Props {
		mode: 'create' | 'edit';
		/** Required when mode is 'create'. */
		filamentId?: string;
		/** Required when mode is 'edit'. */
		session?: CalibrationSession;
		onclose: () => void;
		onsuccess: () => void;
	}
	let { mode, filamentId, session, onclose, onsuccess }: Props = $props();

	const initial = untrack(() => session);

	let printerName = $state(initial?.printerName ?? '');
	let nozzleDiameter = $state(initial?.nozzleDiameter != null ? String(initial.nozzleDiameter) : '');
	let notes = $state(initial?.notes ?? '');
	let submitting = $state(false);

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
			const diameter = parseDecimal(nozzleDiameter);
			const body: SessionBody = {
				printer_name: printerName.trim() ? printerName.trim() : null,
				nozzle_diameter: diameter ?? null,
				notes: notes.trim() ? notes.trim() : null
			};
			if (mode === 'create') {
				if (!filamentId) throw new Error('SessionFormModal: filamentId is required to create a session');
				await createSession(filamentId, body);
			} else if (initial) {
				await updateSession(initial.id, body);
			}
			onsuccess();
			onclose();
		} catch (e) {
			console.error('Failed to save calibration session', e);
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
		aria-labelledby="session-form-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="session-form-title">
				{mode === 'create'
					? ng.calibration_session_form_create_title()
					: ng.calibration_session_form_edit_title()}
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
			<FieldGrid labelWidth="150px">
				<Field label={ng.calibration_fields_printer_name()}>
					<EditableField
						value={printerName}
						placeholder={ng.calibration_printer_name_placeholder()}
						oninput={(v) => (printerName = v)}
					/>
				</Field>
				<Field label={ng.calibration_fields_nozzle_diameter()}>
					<NumberInput bind:value={nozzleDiameter} min={0.1} max={2} step={0.1} unit="mm" />
				</Field>
				<Field label={ng.calibration_fields_notes()}>
					<textarea class="comment" rows="3" placeholder={ng.calibration_optional_notes()} bind:value={notes}
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
		padding: 10vh 16px 16px;
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
