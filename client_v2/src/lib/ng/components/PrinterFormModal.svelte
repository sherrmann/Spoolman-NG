<script lang="ts">
	/** Add or edit one printer (#413). The caller saves; this dialog validates the form. */
	import Button from '$components/Button.svelte';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import NgFormModal from './NgFormModal.svelte';
	import { PRINTER_COMMENT_MAX, PRINTER_NAME_MAX, validatePrinter } from '$lib/ng/printers';
	import type { Printer } from '$lib/ng/types';

	interface Props {
		printer?: Printer;
		busy?: boolean;
		error?: string;
		onclose: () => void;
		onsubmit: (name: string, comment: string) => void;
	}
	let { printer, busy = false, error = '', onclose, onsubmit }: Props = $props();

	// Seeded once from the printer being edited; the dialog is remounted per row.
	// svelte-ignore state_referenced_locally
	let name = $state(printer?.name ?? '');
	// svelte-ignore state_referenced_locally
	let comment = $state(printer?.comment ?? '');
	let invalid = $state<'name' | 'comment' | null>(null);

	function submit() {
		invalid = validatePrinter(name, comment);
		if (invalid) return;
		onsubmit(name, comment);
	}
</script>

<NgFormModal
	title={printer ? ng.settings_printers_edit_title() : ng.settings_printers_add_title()}
	{busy}
	{onclose}
	onsubmit={submit}
>
	<label class="fld">
		<span class="lbl">{ng.printer_fields_name()}</span>
		<input
			class="in"
			bind:value={name}
			maxlength={PRINTER_NAME_MAX}
			class:invalid={invalid === 'name'}
			aria-invalid={invalid === 'name'}
			disabled={busy}
		/>
	</label>
	<label class="fld">
		<span class="lbl">{ng.printer_fields_comment()}</span>
		<textarea
			class="in"
			rows="2"
			bind:value={comment}
			maxlength={PRINTER_COMMENT_MAX}
			class:invalid={invalid === 'comment'}
			aria-invalid={invalid === 'comment'}
			disabled={busy}></textarea>
	</label>
	{#if error}<div class="error" role="alert">{error}</div>{/if}
	{#snippet footer()}
		<Button variant="outline" disabled={busy} onclick={onclose}>{m['buttons.cancel']()}</Button>
		<Button variant="primary" type="submit" disabled={busy}>{m['buttons.save']()}</Button>
	{/snippet}
</NgFormModal>

<style>
	.fld {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.lbl {
		font-size: 12px;
		color: var(--text-muted);
	}
	.in {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 7px 10px;
		font-size: 13px;
		font-family: inherit;
	}
	.in:focus {
		border-color: var(--accent);
	}
	.in.invalid {
		border-color: var(--danger);
	}
	.error {
		color: var(--danger-soft);
		font-size: 12px;
	}
</style>
