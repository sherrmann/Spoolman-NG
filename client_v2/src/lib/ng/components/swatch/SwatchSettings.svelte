<script lang="ts">
	/**
	 * Spoolman NG fork addition (#415 step 3): the default swatch style, with a preview on two
	 * example filaments -- one light, one dark -- so both marking colours show. Ported from the
	 * classic client's `pages/settings/swatchSettings.tsx`.
	 *
	 * Renders nothing for a non-administrator, like every fork settings panel: the write would
	 * be refused. Saves on change, optimistically with a rollback, like the unit-scaling switch.
	 */
	import NgSettingsSection from '$lib/ng/components/NgSettingsSection.svelte';
	import SwatchPreview from './SwatchPreview.svelte';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { currentUserIsAdmin } from '$lib/ng/me';
	import { apiErrorMessage } from '$lib/ng/errors';
	import { SWATCH_STYLES, buildSwatchLayoutForStyle, getSwatchStyle, type SwatchInput } from '$lib/ng/swatch';
	import { loadSwatchStyle, saveSwatchStyle } from '$lib/ng/swatchStyleSetting';
	import { swatchStyleName } from '$lib/ng/swatchText';
	import * as m from '$lib/paraglide/messages';

	// The classic client's two example filaments, so the preview reads the same in both.
	const SAMPLE_LIGHT: SwatchInput = {
		id: 42,
		name: 'Sunrise Yellow',
		vendorName: 'Vendor',
		material: 'PLA',
		diameterMm: 1.75,
		weightG: 1000,
		extruderTempC: 215,
		bedTempC: 60,
		articleNumber: 'ART-0042',
		colorHexes: ['f5c211'],
		qrPayload: 'WEB+SPOOLMAN:F-42'
	};
	const SAMPLE_DARK: SwatchInput = {
		...SAMPLE_LIGHT,
		id: 7,
		name: 'Galaxy Black',
		material: 'PETG',
		extruderTempC: 240,
		bedTempC: 80,
		articleNumber: 'ART-0007',
		colorHexes: ['23233a'],
		qrPayload: 'WEB+SPOOLMAN:F-7'
	};

	let show = $state(false);
	let styleKey = $state(getSwatchStyle(null).key);
	// Set once the administrator has chosen, so a load that lands after that choice does not
	// put the old value back on screen.
	let chosen = false;

	$effect(() => {
		currentUserIsAdmin()
			.then((admin) => (show = admin))
			.catch(() => {});
		const ctrl = new AbortController();
		loadSwatchStyle(ctrl.signal).then((k) => {
			if (!chosen) styleKey = k;
		});
		return () => ctrl.abort();
	});

	async function choose(key: string) {
		chosen = true;
		const previous = styleKey;
		styleKey = key;
		try {
			await saveSwatchStyle(key);
			toasts.success(m['notifications.saveSuccessful']());
		} catch (e) {
			// Only undo this choice if it is still the one showing; a later one stands.
			if (styleKey === key) styleKey = previous;
			toasts.error(apiErrorMessage(e));
		}
	}
</script>

{#if show}
	<NgSettingsSection title={ng.settings_swatch_tab()}>
		<div class="body">
			<label class="row">
				<span class="lbl">{ng.settings_swatch_default_style_label()}</span>
				<select class="sel" value={styleKey} onchange={(e) => choose(e.currentTarget.value)}>
					{#each SWATCH_STYLES as s (s.key)}
						<option value={s.key}>{swatchStyleName(s.key)}</option>
					{/each}
				</select>
			</label>
			<p class="intro">{ng.settings_swatch_preview_description()}</p>
			<div class="samples">
				{#each [SAMPLE_LIGHT, SAMPLE_DARK] as sample (sample.id)}
					<div class="sample">
						<SwatchPreview
							layout={buildSwatchLayoutForStyle(sample, styleKey)}
							label={`${swatchStyleName(styleKey)} · ${sample.name}`}
						/>
					</div>
				{/each}
			</div>
		</div>
	</NgSettingsSection>
{/if}

<style>
	.body {
		padding: 12px 14px;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 12px;
		font-size: 13px;
	}
	.lbl {
		color: var(--text-2);
	}
	.sel {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 5px 8px;
		font-size: 13px;
	}
	.intro {
		font-size: 12px;
		color: var(--text-muted);
		margin: 10px 0 6px;
	}
	.samples {
		display: flex;
		flex-wrap: wrap;
		gap: 16px;
	}
	.sample {
		flex: 1 1 200px;
		max-width: 320px;
	}
</style>
