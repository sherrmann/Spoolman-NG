<script lang="ts">
	/**
	 * Spoolman NG fork addition: the SpoolmanDB catalogue fields on the new-filament form, in its
	 * "Advanced specs" block (#415 follow-up; see docs/design/filament-parity.md). The same five
	 * choices as the inspector's rows (FilamentCatalogueFields.svelte), written into the draft
	 * rather than saved, since the filament does not exist yet.
	 *
	 * A duplicate starts with the source filament's values (`filamentDraftFrom`); a blank form
	 * starts with all five unknown, and unknown is not sent (`catalogueForCreate`).
	 */
	import type { FilamentDraft } from '$lib/filament/draft';
	import { ng } from '$lib/ng/i18n';
	import { optionText, yesNoText } from '$lib/ng/filamentCatalogueText';
	import { FINISHES, PATTERNS, SPOOL_TYPES, type CatalogueFields } from '$lib/ng/filamentCatalogue';

	let { draft = $bindable() }: { draft: FilamentDraft } = $props();

	function set(patch: Partial<CatalogueFields>) {
		draft.ng = { ...draft.ng, ...patch };
	}

	function setEnum(key: 'spoolType' | 'finish' | 'pattern', value: string) {
		set({ [key]: value === '' ? null : value });
	}

	function setBool(key: 'translucent' | 'glow', value: string) {
		set({ [key]: value === '' ? null : value === 'true' });
	}

	const boolValue = (v: boolean | null | undefined) => (v === null || v === undefined ? '' : String(v));
</script>

{#snippet choice(
	label: string,
	value: string,
	options: readonly string[],
	text: (v: string) => string,
	set: (v: string) => void
)}
	<label>
		{label}
		<select {value} onchange={(e) => set(e.currentTarget.value)}>
			<option value="">—</option>
			{#each options as o (o)}
				<option value={o}>{text(o)}</option>
			{/each}
		</select>
	</label>
{/snippet}

<div class="form">
	{@render choice(
		ng.filament_fields_spool_type(),
		draft.ng?.spoolType ?? '',
		SPOOL_TYPES,
		(v) => optionText('spool_type', v),
		(v) => setEnum('spoolType', v)
	)}
	{@render choice(
		ng.filament_fields_finish(),
		draft.ng?.finish ?? '',
		FINISHES,
		(v) => optionText('finish', v),
		(v) => setEnum('finish', v)
	)}
	{@render choice(
		ng.filament_fields_pattern(),
		draft.ng?.pattern ?? '',
		PATTERNS,
		(v) => optionText('pattern', v),
		(v) => setEnum('pattern', v)
	)}
	{@render choice(
		ng.filament_fields_translucent(),
		boolValue(draft.ng?.translucent),
		['true', 'false'],
		(v) => yesNoText(v === 'true'),
		(v) => setBool('translucent', v)
	)}
	{@render choice(
		ng.filament_fields_glow(),
		boolValue(draft.ng?.glow),
		['true', 'false'],
		(v) => yesNoText(v === 'true'),
		(v) => setBool('glow', v)
	)}
</div>

<style>
	/* The grid and field sizes of NewFilamentCards' own `.form`, whose styles are scoped to it. The
	   one difference is the background: its text inputs are transparent, but a transparent
	   <select> leaves the open option list on the browser's default colours, light text on white
	   in the dark theme. `--input-bg`, as the custom-field selects in the same card use. */
	.form {
		display: grid;
		grid-template-columns: 1fr 1fr 1fr;
		gap: 12px;
		margin-top: 14px;
	}
	label {
		display: block;
		font-size: 11.5px;
		color: var(--text-muted);
	}
	select {
		width: 100%;
		border: 1px solid var(--border-strong);
		background: var(--input-bg);
		border-radius: 7px;
		padding: 9px 12px;
		color: var(--text);
		font-size: 13px;
		margin-top: 5px;
	}
	select:focus {
		border-color: var(--accent);
	}
	@media (max-width: 620px) {
		.form {
			grid-template-columns: 1fr 1fr;
		}
	}
</style>
