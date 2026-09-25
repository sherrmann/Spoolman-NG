<script lang="ts">
	/**
	 * Spoolman NG fork addition (#412): what to do with the selected spools. Renders nothing
	 * while nothing is selected.
	 *
	 * Which archive action is offered comes from the selection itself, not from the view: this
	 * client lists archived and active spools together once "Archived" is on, so a mixed
	 * selection is ordinary, and it gets both buttons.
	 */
	import Button from '$components/Button.svelte';
	import ConfirmDialog from '$components/ConfirmDialog.svelte';
	import BulkEditModal from './BulkEditModal.svelte';
	import * as m from '$lib/paraglide/messages';
	import { ng, plural } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { spoolSource } from '$lib/api/spoolSource';
	import { librarySelection, selectionSummary } from '$lib/ng/librarySelection.svelte';
	import { bulkApply } from '$lib/ng/bulkPatch';
	import type { SpoolPatch } from '$lib/types';

	let summary = $derived(selectionSummary(librarySelection.selected.values()));
	let editing = $state(false);
	let confirming = $state<'archive' | 'unarchive' | null>(null);
	let busy = $state(false);

	/** The spools the pending archive action applies to: only those it would change. */
	let targets = $derived(confirming === 'archive' ? summary.active : summary.archived);

	function describe(ids: number[]): string[] {
		const names = ids.slice(0, 8).map((id) => {
			const vm = librarySelection.selected.get(id);
			return vm ? `${vm.idLabel} ${vm.filament.name}`.trim() : `#${id}`;
		});
		return ids.length > names.length ? [...names, '…'] : names;
	}

	async function run(ids: number[], write: (id: number) => Promise<unknown>) {
		busy = true;
		try {
			const { ok, failed } = await bulkApply(ids, write);
			if (failed.length === 0) toasts.success(plural('spool_bulk_applied', ok.length));
			else toasts.error(plural('spool_bulk_applied_partial', ok.length, { failed: failed.length }));
			// What failed stays selected, so it can be retried; everything else is done.
			librarySelection.retain(failed.map((f) => f.id));
		} finally {
			busy = false;
			editing = false;
			confirming = null;
		}
	}

	function applyEdit(patch: SpoolPatch) {
		run([...librarySelection.selected.keys()], (id) => spoolSource.saveSpool(id, patch));
	}

	function applyArchive() {
		const archived = confirming === 'archive';
		run(targets, (id) => spoolSource.setSpoolArchived(id, archived));
	}
</script>

{#if librarySelection.count > 0}
	<div class="bar" role="region" aria-label={plural('spool_bulk_selected', librarySelection.count)}>
		<span class="count">{plural('spool_bulk_selected', librarySelection.count)}</span>
		<span class="actions">
			<Button disabled={busy} onclick={() => (editing = true)}>{m['buttons.edit']()}</Button>
			{#if summary.active.length > 0}
				<Button variant="outline" disabled={busy} onclick={() => (confirming = 'archive')}
					>{m['buttons.archive']()}</Button
				>
			{/if}
			{#if summary.archived.length > 0}
				<Button variant="outline" disabled={busy} onclick={() => (confirming = 'unarchive')}>
					{m['buttons.unArchive']()}
				</Button>
			{/if}
			<Button variant="ghost" disabled={busy} onclick={() => librarySelection.clear()}>
				{ng.spool_bulk_clear_selection()}
			</Button>
		</span>
	</div>
{/if}

{#if editing}
	<BulkEditModal
		count={librarySelection.count}
		{busy}
		onclose={() => (editing = false)}
		onapply={applyEdit}
	/>
{/if}

<ConfirmDialog
	open={confirming !== null}
	title={plural(
		confirming === 'unarchive' ? 'spool_bulk_unarchive_confirm' : 'spool_bulk_archive_confirm',
		targets.length
	)}
	lines={describe(targets)}
	confirmLabel={confirming === 'unarchive' ? m['buttons.unArchive']() : m['buttons.archive']()}
	onconfirm={applyArchive}
	onclose={() => (confirming = null)}
	{busy}
/>

<style>
	.bar {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px 12px;
		padding: 8px 14px;
		border-top: 1px solid var(--border);
		background: var(--accent-wash);
	}
	.count {
		font-size: 12px;
		font-weight: 600;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-left: auto;
	}
</style>
