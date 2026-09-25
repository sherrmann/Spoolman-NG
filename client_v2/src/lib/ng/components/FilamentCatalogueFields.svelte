<script lang="ts">
	/**
	 * Spoolman NG fork addition (#415 step 1): the SpoolmanDB catalogue fields as five rows of the
	 * filament inspector's specs grid.
	 *
	 * Every row can go back to unknown ("—"), which is what the database stores until someone
	 * says. Translucent and glow are three-way for the same reason: "no" is information that
	 * unknown is not.
	 *
	 * The rows save through a saver of their own, keyed by field, rather than the inspector's:
	 * that one merges a pending patch one level deep, so a whole `ng` object would replace the
	 * previous one, and a live update landing between two quick edits could revert the first.
	 * Here each edit adds one key to the pending patch, and only the keys edited are sent. It is
	 * debounced and reports to the save indicator like the inspector's.
	 */
	import Field from '$lib/components/Field.svelte';
	import type { Filament, FilamentPatch } from '$lib/types';
	import { inventory } from '$lib/stores/inventory.svelte';
	import { spoolSource } from '$lib/api/spoolSource';
	import { makeSaver } from '$lib/utils/saver';
	import { trackSave } from '$lib/utils/autosave';
	import { ng } from '$lib/ng/i18n';
	import { optionText, yesNoText } from '$lib/ng/filamentCatalogueText';
	import {
		EMPTY_FILAMENT_NG,
		FINISHES,
		PATTERNS,
		SPOOL_TYPES,
		type FilamentNg
	} from '$lib/ng/filamentCatalogue';

	let { filament }: { filament: Filament } = $props();

	let current = $derived(filament.ng ?? EMPTY_FILAMENT_NG);

	// `filamentNgPatchToApi` sends only the keys a partial `ng` carries, so the cast is sound;
	// the view model's patch type just has no partial form of `ng`.
	// A filament deleted with an edit still pending has left the cache by the time this saver
	// flushes (on unmount, when the inspector clears its selection), and a PATCH would only earn
	// an error toast under "Filament deleted"; the inspector cancels its own savers for the same
	// reason, but cannot reach this one.
	const saver = makeSaver<string, Partial<FilamentNg>>((id, patch) =>
		inventory.filamentById(id)
			? trackSave(spoolSource.saveFilament(id, { ng: patch } as FilamentPatch))
			: Promise.resolve()
	);
	$effect(() => () => saver.flush());

	function set(patch: Partial<FilamentNg>) {
		inventory.patchFilament(filament.id, { ng: { ...current, ...patch } });
		saver.push(filament.id, patch);
	}

	function setEnum(key: 'spoolType' | 'finish' | 'pattern', value: string) {
		set({ [key]: value === '' ? null : value });
	}

	function setBool(key: 'translucent' | 'glow', value: string) {
		set({ [key]: value === '' ? null : value === 'true' });
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
