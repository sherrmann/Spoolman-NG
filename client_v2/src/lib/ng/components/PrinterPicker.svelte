<script lang="ts">
	/**
	 * The printer field of the add-spool form (#75 / #413).
	 *
	 * Shown only once at least one printer exists, so the form stays as it was for anyone who
	 * does not track printers -- the React client makes the same choice. The value is the
	 * printer id, or undefined for none; the modal puts it on the create body as `printer_id`.
	 *
	 * A plain `<label>` wrapping its control, like every other field in that form, so it reads
	 * and is found the same way.
	 */
	import { ng } from '$lib/ng/i18n';
	import { listPrinters } from '$lib/ng/api';
	import type { Printer } from '$lib/ng/types';

	let { value = $bindable() }: { value: number | undefined } = $props();

	let printers = $state<Printer[]>([]);

	$effect(() => {
		const controller = new AbortController();
		listPrinters(controller.signal)
			.then((p) => (printers = p))
			.catch(() => (printers = []));
		return () => controller.abort();
	});
</script>

{#if printers.length}
	<label>
		{ng.spool_fields_printer()}
		<select
			value={value ?? ''}
			onchange={(e) => {
				const v = e.currentTarget.value;
				value = v ? Number(v) : undefined;
			}}
		>
			<option value="">{ng.spool_fields_no_printer()}</option>
			{#each printers as p (p.id)}
				<option value={p.id}>{p.name}</option>
			{/each}
		</select>
		<span class="hint">{ng.spool_fields_help_printer()}</span>
	</label>
{/if}

<style>
	label {
		display: flex;
		flex-direction: column;
		gap: 5px;
		font-size: 12px;
		color: var(--text-muted);
	}
	select {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 7px 10px;
		font-size: 13px;
	}
	select:focus {
		border-color: var(--accent);
	}
	.hint {
		font-size: 11px;
		color: var(--text-dim);
	}
</style>
