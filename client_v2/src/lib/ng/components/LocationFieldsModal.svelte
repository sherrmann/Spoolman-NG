<script lang="ts">
	// Edits one Location row's custom-field values (#103) -- opened from the "Custom fields"
	// button on a /locations row. The caller only mounts this while `listLocationFields()` has
	// already returned at least one definition (see routes/locations/+page.svelte), so `defs` is
	// never empty here.
	//
	// Deliberately its own small Save/Cancel form rather than $components/ExtraFieldsSection:
	// that component autosaves field-by-field against the live `fields.ensure()` store, which
	// fits an entity whose extra fields are each their own PATCH. A Location's `extra` is instead
	// written as one whole object via `PATCH /locations/{id}` (see $lib/ng/api's updateLocation),
	// so edits are held in a local draft until Save, same shape as the fork's other dialogs.
	import Button from '$components/Button.svelte';
	import Field from '$components/Field.svelte';
	import FieldGrid from '$components/FieldGrid.svelte';
	import ExtraFieldInput from '$components/ExtraFieldInput.svelte';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { untrack } from 'svelte';
	import { updateLocation, asFieldDef, type LocationFieldDef } from '$lib/ng/api';
	import { toasts } from '$lib/stores/toasts.svelte';
	import type { Location } from '$lib/ng/types';

	interface Props {
		location: Location;
		defs: LocationFieldDef[];
		onclose: () => void;
		onsuccess: () => void;
	}
	let { location, defs, onclose, onsuccess }: Props = $props();

	// This dialog is only ever mounted fresh for one location (the caller renders it inside an
	// `{#if editingFieldsFor}`, same as MarkOrderedDialog's own doc comment on why upstream's
	// order dialogs are conditionally rendered), so `location` never changes out from under it --
	// but reading a prop directly in a `$state` initializer still trips Svelte's
	// "state_referenced_locally" check, since in general nothing stops a prop from changing
	// later. `untrack` says that's fine here, the same way OrderDetailsModal.svelte's
	// `untrack(() => order)` does for its own once-only seeding.
	const initial = untrack(() => location);

	// Local draft of the JSON-encoded values, seeded from the row's current `extra`. `undefined`
	// means "cleared" -- ExtraFieldInput's own convention (see its doc comment) -- and is dropped
	// from the PATCH body entirely rather than sent as a literal null, same as how the field
	// started out unset.
	let draft = $state<Record<string, string | undefined>>({ ...initial.extra });
	let submitting = $state(false);

	function onFieldChange(key: string, json: string | undefined) {
		draft = { ...draft, [key]: json };
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

	async function save() {
		if (submitting) return;
		submitting = true;
		try {
			const extra: Record<string, string> = {};
			for (const [key, value] of Object.entries(draft)) {
				if (value !== undefined) extra[key] = value;
			}
			await updateLocation(location.id, { extra });
			toasts.success(ng.locations_fields_saved());
			onsuccess();
			onclose();
		} catch (e) {
			console.error('Failed to save location fields', e);
			toasts.error(ng.locations_fields_save_error());
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
		aria-labelledby="location-fields-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="location-fields-title">
				{ng.locations_fields_title({ name: location.name })}
			</span>
			<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
		</div>

		<div class="body">
			<FieldGrid>
				{#each defs as def (def.key)}
					<Field label={def.name}>
						<ExtraFieldInput
							field={asFieldDef(def)}
							value={draft[def.key]}
							onchange={(json) => onFieldChange(def.key, json)}
						/>
					</Field>
				{/each}
			</FieldGrid>
		</div>

		<div class="foot">
			<Button variant="outline" disabled={submitting} onclick={close}>{m['buttons.cancel']()}</Button>
			<Button variant="primary" disabled={submitting} onclick={save}>{ng.buttons_save()}</Button>
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
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px 16px;
		flex: none;
	}
</style>
