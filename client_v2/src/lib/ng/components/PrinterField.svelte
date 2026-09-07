<script lang="ts">
	/**
	 * The "Printer" row of the spool inspector (#75 / #413): which printer the spool is loaded
	 * on, changeable in place like the fields around it.
	 *
	 * Upstream's `Spool` has no printer field and its mapper drops the nested object, so this
	 * row fetches the one spool it shows and writes `printer_id` straight to the API instead of
	 * going through the inspector's debounced saver -- which would need the vendored type and
	 * mapper widened. The printer list itself comes from the shared store, loaded once. Renders
	 * nothing while no printer exists, so the inspector is unchanged for anyone who does not
	 * track printers.
	 */
	import Field from '$components/Field.svelte';
	import type { Spool } from '$lib/types';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { setSpoolPrinter, spoolPrinterId } from '$lib/ng/api';
	import { apiErrorMessage } from '$lib/ng/errors';
	import { printers } from '$lib/ng/printersState.svelte';

	let { spool }: { spool: Spool } = $props();

	let current = $state<number | undefined>(undefined);
	let ready = $state(false);

	$effect(() => {
		void printers.load();
	});

	$effect(() => {
		const id = spool.id;
		const controller = new AbortController();
		ready = false;
		spoolPrinterId(id, controller.signal)
			.then((assigned) => {
				current = assigned;
				ready = true;
			})
			.catch(() => {});
		return () => controller.abort();
	});

	async function change(raw: string) {
		const next = raw ? Number(raw) : undefined;
		const previous = current;
		current = next;
		try {
			await setSpoolPrinter(spool.id, next ?? null);
		} catch (e) {
			current = previous;
			toasts.error(apiErrorMessage(e));
		}
	}
</script>

{#if ready && printers.items.length}
	<Field label={ng.spool_fields_printer()} help={ng.spool_fields_help_printer()}>
		<select
			class="sel"
			aria-label={ng.spool_fields_printer()}
			value={current ?? ''}
			onchange={(e) => change(e.currentTarget.value)}
		>
			<option value="">{ng.spool_fields_no_printer()}</option>
			{#each printers.items as p (p.id)}
				<option value={p.id}>{p.name}</option>
			{/each}
		</select>
	</Field>
{/if}

<style>
	/* Dashed underline like EditableField, so it reads as editable in place. */
	.sel {
		width: 100%;
		max-width: 100%;
		background: transparent;
		border: none;
		border-bottom: 1px dashed var(--border-strong);
		border-radius: 0;
		color: var(--text);
		padding: 2px 0;
		font-size: inherit;
		cursor: pointer;
	}
	.sel:focus {
		outline: none;
		border-bottom-color: var(--accent);
	}
</style>
