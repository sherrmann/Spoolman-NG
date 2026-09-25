<script lang="ts">
	/**
	 * Spoolman NG fork addition (#415 step 3): the filament inspector's "3D-printable swatch"
	 * icon, beside duplicate and delete, and the download dialog it opens. The dialog is only
	 * mounted while open, so the inspector pays nothing for it otherwise.
	 */
	import Button from '$components/Button.svelte';
	import Box from '@lucide/svelte/icons/box';
	import type { Filament } from '$lib/types';
	import { ng } from '$lib/ng/i18n';
	import SwatchDownloadDialog from './SwatchDownloadDialog.svelte';

	let { filament }: { filament: Filament } = $props();
	let open = $state(false);
</script>

<Button
	variant="ghost"
	title={ng.filament_swatch_title()}
	ariaLabel={ng.filament_swatch_title()}
	onclick={() => (open = true)}><Box size={15} /></Button
>
{#if open}
	<SwatchDownloadDialog {filament} onclose={() => (open = false)} />
{/if}
