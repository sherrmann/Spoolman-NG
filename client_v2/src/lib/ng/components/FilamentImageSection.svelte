<script lang="ts">
	/**
	 * Spoolman NG fork addition (#415 step 2): a filament's reference photo in its inspector,
	 * under the manufacturer.
	 *
	 * The photo is not a filament field: it has its own endpoints, so it saves the moment it is
	 * picked or removed rather than through the inspector's debounced saver. Both endpoints
	 * broadcast a filament update, so another open client learns that a photo was added or
	 * removed; a photo replaced elsewhere shows the next time the filament is opened.
	 */
	import SectionLabel from '$lib/components/SectionLabel.svelte';
	import ImagePlus from '@lucide/svelte/icons/image-plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import type { Filament } from '$lib/types';
	import { inventory } from '$lib/stores/inventory.svelte';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { mapFilament } from '$lib/api/map';
	import { isAbortError } from '$lib/api/http';
	import { ng } from '$lib/ng/i18n';
	import { EMPTY_FILAMENT_NG } from '$lib/ng/filamentCatalogue';
	import {
		cachedFilamentImage,
		deleteFilamentImage,
		loadFilamentImage,
		prepareImageForUpload,
		uploadFilamentImage
	} from '$lib/ng/filamentImage';

	let { filament }: { filament: Filament } = $props();

	let id = $derived(filament.id);
	let hasImage = $derived(filament.ng?.hasImage ?? false);
	let src = $state<string | null>(null);
	let busy = $state(false);
	// Bumped after an upload, so the same filament's photo is fetched again.
	let version = $state(0);
	let input = $state<HTMLInputElement>();

	$effect(() => {
		const current = id;
		void version;
		if (!hasImage) {
			src = null;
			return;
		}
		// Show what is already held at once, and swap in the revalidated copy when it lands.
		src = cachedFilamentImage(current);
		const ctrl = new AbortController();
		loadFilamentImage(current, ctrl.signal)
			.then((url) => {
				if (!ctrl.signal.aborted) src = url;
			})
			.catch((e) => {
				// A network failure keeps whatever is shown.
				if (!isAbortError(e, ctrl.signal)) console.error('Failed to load filament photo', e);
			});
		return () => ctrl.abort();
	});

	async function picked(e: Event & { currentTarget: HTMLInputElement }) {
		const file = e.currentTarget.files?.[0];
		// Cleared at once, so picking the same file again still fires a change.
		e.currentTarget.value = '';
		if (!file) return;
		const target = id;
		busy = true;
		try {
			let prepared;
			try {
				prepared = await prepareImageForUpload(file);
			} catch (err) {
				console.error('Could not read the picked image', err);
				toasts.error(ng.filament_image_prepare_error());
				return;
			}
			const updated = await uploadFilamentImage(target, prepared);
			inventory.upsertFilament(mapFilament(updated));
			version++;
			toasts.success(ng.filament_image_uploaded());
		} catch (err) {
			console.error('Failed to upload filament photo', err);
			toasts.error(ng.filament_image_upload_error());
		} finally {
			busy = false;
		}
	}

	async function remove() {
		const target = id;
		busy = true;
		try {
			await deleteFilamentImage(target);
			const f = inventory.filamentById(target);
			if (f) inventory.patchFilament(target, { ng: { ...(f.ng ?? EMPTY_FILAMENT_NG), hasImage: false } });
			toasts.success(ng.filament_image_removed());
		} catch (err) {
			console.error('Failed to remove filament photo', err);
			toasts.error(ng.filament_image_remove_error());
		} finally {
			busy = false;
		}
	}
</script>

{#snippet actions()}
	<span class="sec-actions">
		<button class="link" disabled={busy} onclick={() => input?.click()}
			><ImagePlus size={13} />
			{hasImage ? ng.filament_image_replace() : ng.filament_image_upload()}</button
		>
		{#if hasImage}
			<button class="link danger" disabled={busy} onclick={remove}
				><Trash2 size={13} /> {ng.filament_image_remove()}</button
			>
		{/if}
	</span>
{/snippet}

<div class="photo-section">
	<SectionLabel right={actions}>{ng.filament_fields_image()}</SectionLabel>
	<input bind:this={input} type="file" accept="image/*" hidden onchange={picked} />
	{#if hasImage && src}
		<img {src} alt={ng.filament_fields_image()} />
	{/if}
</div>

<style>
	.photo-section {
		margin-top: 8px;
	}
	img {
		display: block;
		max-width: 100%;
		max-height: 240px;
		object-fit: contain;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-soft);
	}
	/* The same look as the manufacturer section's actions just above (VendorSection). */
	.link {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		font-size: 11.5px;
		color: var(--accent-link);
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		font-family: inherit;
	}
	.link.danger {
		color: var(--danger-soft);
	}
	.link:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.sec-actions {
		display: inline-flex;
		align-items: center;
		gap: 14px;
	}
</style>
