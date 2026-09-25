<script lang="ts">
	/**
	 * Spoolman NG fork addition (#415 step 3): preview and download a filament's 3D-printable
	 * swatch card as a 3MF. Ported from the classic client's `components/swatchDownloadModal.tsx`.
	 *
	 * The style starts from the server-wide `swatch_style` setting and can be changed for this
	 * one download. The QR code carries the compact `WEB+SPOOLMAN:F-<id>` code by default, or a
	 * link to the filament (base URL setting, else this page's origin), the same two forms the
	 * label designer prints; the choice is remembered in this browser.
	 */
	import Button from '$components/Button.svelte';
	import NgFormModal from '$lib/ng/components/NgFormModal.svelte';
	import SwatchPreview from './SwatchPreview.svelte';
	import * as m from '$lib/paraglide/messages';
	import type { Filament } from '$lib/types';
	import { inventory } from '$lib/stores/inventory.svelte';
	import { settings } from '$lib/stores/settings.svelte';
	import { ng } from '$lib/ng/i18n';
	import {
		SWATCH_STYLES,
		buildSwatchLayoutForStyle,
		generateFilamentSwatch,
		getSwatchStyle,
		saveBinaryFile,
		swatchInputFromFilament
	} from '$lib/ng/swatch';
	import { loadSwatchStyle } from '$lib/ng/swatchStyleSetting';
	import { swatchStyleName } from '$lib/ng/swatchText';

	let { filament, onclose }: { filament: Filament; onclose: () => void } = $props();

	const URL_KEY = 'spoolman-ng-swatch-qr-url';

	function readUseUrl(): boolean {
		try {
			return localStorage.getItem(URL_KEY) === 'true';
		} catch {
			return false;
		}
	}

	let useUrl = $state(readUseUrl());
	function setUseUrl(v: boolean) {
		useUrl = v;
		try {
			localStorage.setItem(URL_KEY, String(v));
		} catch {
			/* remembering the choice is a convenience */
		}
	}

	let defaultStyle = $state(getSwatchStyle(null).key);
	let override = $state<string | null>(null);
	let styleKey = $derived(override ?? defaultStyle);
	$effect(() => {
		const ctrl = new AbortController();
		loadSwatchStyle(ctrl.signal).then((k) => (defaultStyle = k));
		return () => ctrl.abort();
	});

	let root = $derived((settings.baseUrl || window.location.origin).replace(/\/+$/, ''));
	let payload = $derived(
		useUrl ? `${root}/filament/show/${filament.id}` : `WEB+SPOOLMAN:F-${filament.id}`
	);
	let input = $derived(
		swatchInputFromFilament(filament, {
			qrPayload: payload,
			vendorName: inventory.vendorById(filament.vendorId)?.name
		})
	);
	let layout = $derived(buildSwatchLayoutForStyle(input, styleKey));
	let colour = $derived(
		layout.markingColor === 'white' ? ng.filament_swatch_marking_white() : ng.filament_swatch_marking_black()
	);

	function download() {
		const { data, filename } = generateFilamentSwatch(input, styleKey);
		saveBinaryFile(data, filename);
		onclose();
	}
</script>

<NgFormModal title={ng.filament_swatch_title()} {onclose} onsubmit={download}>
	<p class="hint">
		{ng.filament_swatch_description({ width: layout.widthMm, height: layout.heightMm, color: colour })}
	</p>
	<div class="preview">
		<SwatchPreview {layout} label={ng.filament_swatch_title()} />
	</div>
	{#if layout.textLines.some((l) => l.truncated)}
		<p class="warn" role="status">{ng.filament_swatch_truncated_warning()}</p>
	{/if}
	<label class="fld">
		<span class="lbl">{ng.filament_swatch_style()}</span>
		<select class="in" value={styleKey} onchange={(e) => (override = e.currentTarget.value)}>
			{#each SWATCH_STYLES as s (s.key)}
				<option value={s.key}>{swatchStyleName(s.key)}</option>
			{/each}
		</select>
	</label>
	<fieldset class="fld">
		<legend class="lbl" title={ng.printing_qrcode_useHTTPUrl_tooltip()}>
			{ng.printing_qrcode_useHTTPUrl_label()}
		</legend>
		<div class="radios">
			<label
				><input type="radio" name="qr" checked={!useUrl} onchange={() => setUseUrl(false)} />
				{ng.printing_qrcode_useHTTPUrl_options_default()}</label
			>
			<label
				><input type="radio" name="qr" checked={useUrl} onchange={() => setUseUrl(true)} />
				{ng.printing_qrcode_useHTTPUrl_options_url()}</label
			>
		</div>
		<code class="payload">{payload}</code>
	</fieldset>
	<p class="hint">{ng.filament_swatch_print_hint({ color: colour })}</p>
	{#snippet footer()}
		<Button variant="outline" onclick={onclose}>{m['buttons.cancel']()}</Button>
		<Button variant="primary" type="submit">{ng.filament_swatch_download()}</Button>
	{/snippet}
</NgFormModal>

<style>
	.hint {
		font-size: 12px;
		color: var(--text-muted);
		margin: 0;
	}
	.preview {
		padding: 8px 0;
	}
	.warn {
		font-size: 12px;
		color: var(--warning, var(--danger-soft));
		margin: 0;
	}
	fieldset {
		border: none;
		padding: 0;
		margin: 0;
	}
	.radios {
		display: flex;
		gap: 16px;
		font-size: 13px;
	}
	.radios input {
		accent-color: var(--accent);
	}
	.payload {
		font-size: 11px;
		overflow-wrap: anywhere;
		color: var(--text-2);
	}
</style>
