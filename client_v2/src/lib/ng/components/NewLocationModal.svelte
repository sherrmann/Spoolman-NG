<script lang="ts">
	// "New location" dialog for the /locations registry page (#103).
	//
	// The backend puts NO uniqueness constraint on `location.name` -- POSTing a duplicate name
	// returns 200 and creates a second row (see $lib/ng/api's doc comment on
	// getOrCreateLocationByName). So the duplicate check below runs client-side, against the
	// list the caller already loaded, before the POST ever goes out -- there is no 409 to
	// recover from afterwards the way ensureShop() gets to lean on one.
	import Button from '$components/Button.svelte';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { createLocation } from '$lib/ng/api';

	interface Props {
		/** Every existing location name, for the duplicate check. */
		existingNames: string[];
		onclose: () => void;
		onsuccess: () => void;
	}
	let { existingNames, onclose, onsuccess }: Props = $props();

	let name = $state('');
	let error = $state('');
	let submitting = $state(false);

	let dialog = $state<HTMLDivElement>();
	let nameInput = $state<HTMLInputElement>();
	let opener: HTMLElement | null = null;
	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		nameInput?.focus();
		return () => opener?.focus();
	});

	function close() {
		if (!submitting) onclose();
	}

	async function submit() {
		if (submitting) return;
		const trimmed = name.trim();
		if (!trimmed) {
			error = ng.locations_error_empty();
			return;
		}
		if (existingNames.includes(trimmed)) {
			error = ng.locations_error_exists();
			return;
		}
		error = '';
		submitting = true;
		try {
			await createLocation({ name: trimmed });
			onsuccess();
			onclose();
		} catch (e) {
			// No dedicated ng.* string covers a create-request failure (as opposed to the two
			// validation cases above, which do) -- hardcoded English, same as the rename/delete
			// failure messages elsewhere on this page.
			console.error('Failed to create location', e);
			error = ng.locations_create_error();
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
		aria-labelledby="new-location-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="new-location-title">{ng.locations_new_location()}</span>
			<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
		</div>

		<form
			class="body"
			onsubmit={(e) => {
				e.preventDefault();
				submit();
			}}
		>
			<label class="fld">
				<span class="lbl">{ng.locations_location()}</span>
				<input
					class="in"
					bind:value={name}
					bind:this={nameInput}
					class:invalid={!!error}
					aria-invalid={!!error}
					disabled={submitting}
				/>
			</label>
			{#if error}<div class="error" role="alert">{error}</div>{/if}
		</form>

		<div class="foot">
			<Button variant="outline" disabled={submitting} onclick={close}>{m['buttons.cancel']()}</Button>
			<Button variant="primary" disabled={submitting} onclick={submit}>{ng.buttons_create()}</Button>
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
		width: 400px;
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
		padding: 16px 20px 4px;
	}
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
	}
	.in:focus {
		border-color: var(--accent);
	}
	.in.invalid {
		border-color: var(--danger);
	}
	.error {
		margin-top: 10px;
		color: var(--danger-soft);
		font-size: 12px;
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px 16px;
		flex: none;
	}
</style>
