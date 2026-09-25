<script lang="ts">
	/**
	 * Spoolman NG fork addition (#412): change location, lot, price or comment on every selected
	 * spool at once. Tick-to-change, as in the classic client; see bulkEditBody for the rules.
	 */
	import Button from '$components/Button.svelte';
	import NgFormModal from '../NgFormModal.svelte';
	import * as m from '$lib/paraglide/messages';
	import { ng, plural } from '$lib/ng/i18n';
	import { spoolSource } from '$lib/api/spoolSource';
	import { BULK_FIELDS, bulkEditBody, type BulkField } from '$lib/ng/bulkEditBody';
	import type { SpoolPatch } from '$lib/types';
	import { numericInput } from '$lib/utils/numeric';

	interface Props {
		count: number;
		busy: boolean;
		onclose: () => void;
		onapply: (patch: SpoolPatch) => void;
	}
	let { count, busy, onclose, onapply }: Props = $props();

	let ticked = $state<Record<BulkField, boolean>>({
		location: false,
		lot: false,
		price: false,
		comment: false
	});
	let values = $state<Record<BulkField, string>>({ location: '', lot: '', price: '', comment: '' });
	let error = $state<string | null>(null);
	let locations = $state<string[]>([]);

	$effect(() => {
		spoolSource
			.locations()
			.then((l) => (locations = l))
			.catch(() => (locations = []));
	});

	const labels: Record<BulkField, () => string> = {
		location: m['spool.fields.location'],
		lot: m['spool.fields.lotNr'],
		price: m['spool.fields.price'],
		comment: m['spool.fields.comment']
	};

	function submit() {
		const body = bulkEditBody({ ticked, values });
		if ('error' in body) {
			error = body.error === 'nothing' ? ng.spool_bulk_nothing_selected() : ng.spool_bulk_invalid_price();
			return;
		}
		error = null;
		onapply(body.patch);
	}

	const listId = $props.id();
</script>

<NgFormModal title={plural('spool_bulk_edit_title', count)} {busy} {onclose} onsubmit={submit}>
	<p class="help">{ng.spool_bulk_edit_help()}</p>
	{#each BULK_FIELDS as field (field)}
		<div class="fld">
			<label class="lbl tick">
				<input type="checkbox" bind:checked={ticked[field]} disabled={busy} />
				{labels[field]()}
			</label>
			{#if field === 'comment'}
				<textarea
					class="in"
					rows="2"
					bind:value={values.comment}
					oninput={() => (ticked.comment = true)}
					disabled={busy}
					aria-label={labels.comment()}></textarea>
			{:else if field === 'price'}
				<input
					class="in"
					bind:value={values.price}
					oninput={() => (ticked.price = true)}
					inputmode="decimal"
					use:numericInput={{ negative: false }}
					disabled={busy}
					aria-label={labels.price()}
				/>
			{:else}
				<input
					class="in"
					bind:value={values[field]}
					oninput={() => (ticked[field] = true)}
					list={field === 'location' ? listId : undefined}
					disabled={busy}
					aria-label={labels[field]()}
				/>
			{/if}
		</div>
	{/each}
	<datalist id={listId}>
		{#each locations as l (l)}<option value={l}></option>{/each}
	</datalist>
	{#if error}<div class="error" role="alert">{error}</div>{/if}
	{#snippet footer()}
		<Button variant="outline" disabled={busy} onclick={onclose}>{m['buttons.cancel']()}</Button>
		<Button variant="primary" type="submit" disabled={busy}>{m['buttons.apply']()}</Button>
	{/snippet}
</NgFormModal>

<style>
	.tick {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		cursor: pointer;
	}
	.tick input {
		accent-color: var(--accent);
		margin: 0;
	}
</style>
