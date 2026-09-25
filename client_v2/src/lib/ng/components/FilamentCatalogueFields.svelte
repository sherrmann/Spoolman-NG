<script lang="ts">
	/**
	 * Spoolman NG fork addition (#415 step 1): the SpoolmanDB catalogue fields as five rows of the
	 * filament inspector's specs grid.
	 *
	 * Every row can go back to unknown ("—"), which is what the database stores until someone
	 * says. Translucent and glow are three-way for the same reason: "no" is information that
	 * unknown is not. The inspector's own saver writes the change, so it is debounced and shows
	 * in the save indicator like every other field there.
	 */
	import Field from '$lib/components/Field.svelte';
	import type { Filament } from '$lib/types';
	import { ng } from '$lib/ng/i18n';
	import { optionText, yesNoText } from '$lib/ng/filamentCatalogueText';
	import {
		EMPTY_FILAMENT_NG,
		FINISHES,
		PATTERNS,
		SPOOL_TYPES,
		type FilamentNg
	} from '$lib/ng/filamentCatalogue';

	let { filament, onchange }: { filament: Filament; onchange: (next: FilamentNg) => void } = $props();

	let current = $derived(filament.ng ?? EMPTY_FILAMENT_NG);

	function setEnum<K extends 'spoolType' | 'finish' | 'pattern'>(key: K, value: string) {
		onchange({ ...current, [key]: value === '' ? null : value });
	}

	function setBool(key: 'translucent' | 'glow', value: string) {
		onchange({ ...current, [key]: value === '' ? null : value === 'true' });
	}

	const boolValue = (v: boolean | null) => (v === null ? '' : String(v));
</script>

{#snippet choice(
	label: string,
	value: string,
	options: readonly string[],
	text: (v: string) => string,
	set: (v: string) => void
)}
	<Field {label}>
		<select class="sel" {value} aria-label={label} onchange={(e) => set(e.currentTarget.value)}>
			<option value="">—</option>
			{#each options as o (o)}
				<option value={o}>{text(o)}</option>
			{/each}
		</select>
	</Field>
{/snippet}

{@render choice(
	ng.filament_fields_spool_type(),
	current.spoolType ?? '',
	SPOOL_TYPES,
	(v) => optionText('spool_type', v),
	(v) => setEnum('spoolType', v)
)}
{@render choice(
	ng.filament_fields_finish(),
	current.finish ?? '',
	FINISHES,
	(v) => optionText('finish', v),
	(v) => setEnum('finish', v)
)}
{@render choice(
	ng.filament_fields_pattern(),
	current.pattern ?? '',
	PATTERNS,
	(v) => optionText('pattern', v),
	(v) => setEnum('pattern', v)
)}
{@render choice(
	ng.filament_fields_translucent(),
	boolValue(current.translucent),
	['true', 'false'],
	(v) => yesNoText(v === 'true'),
	(v) => setBool('translucent', v)
)}
{@render choice(
	ng.filament_fields_glow(),
	boolValue(current.glow),
	['true', 'false'],
	(v) => yesNoText(v === 'true'),
	(v) => setBool('glow', v)
)}

<style>
	/* The same look as a choice extra field's select in this grid (ExtraFieldInput). */
	.sel {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 3px 6px;
		font-size: 12.5px;
		width: 200px;
		max-width: 100%;
	}
</style>
