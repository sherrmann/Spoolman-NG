<script lang="ts">
	/**
	 * The printers registry (#75 / #413): list, add, edit, delete.
	 *
	 * Printer extra fields can be defined (the backend registers `extra_fields_printer`) but
	 * are not edited here, which matches the React client's printer form. Renders nothing for a
	 * non-administrator, who cannot write.
	 */
	import Button from '$components/Button.svelte';
	import Card from '$components/Card.svelte';
	import ConfirmDialog from '$components/ConfirmDialog.svelte';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Plus from '@lucide/svelte/icons/plus';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { currentUserIsAdmin } from '$lib/ng/me';
	import { apiErrorMessage } from '$lib/ng/errors';
	import { parseTrans } from '$lib/ng/trans';
	import { createPrinter, deletePrinter, listPrinters, updatePrinter } from '$lib/ng/api';
	import { printerBody } from '$lib/ng/printers';
	import type { Printer } from '$lib/ng/types';
	import PrinterFormModal from './PrinterFormModal.svelte';

	let show = $state(false);
	let printers = $state<Printer[]>([]);
	let paragraphs = $derived(
		parseTrans(ng.settings_printers_description()).map((b) =>
			b.kind === 'block' ? b.inline.map((i) => i.text).join('') : ''
		)
	);

	$effect(() => {
		(async () => {
			if (!(await currentUserIsAdmin())) return;
			printers = await listPrinters();
			show = true;
		})().catch(() => {});
	});

	// `editing` is the printer the open form is for, or null when adding; `formOpen` says
	// whether the form is up at all, since "adding" and "closed" both have no printer.
	let formOpen = $state(false);
	let editing = $state<Printer | null>(null);
	let deleting = $state<Printer | null>(null);
	let busy = $state(false);
	let error = $state('');

	function openAdd() {
		editing = null;
		error = '';
		formOpen = true;
	}
	function openEdit(p: Printer) {
		editing = p;
		error = '';
		formOpen = true;
	}

	async function submit(name: string, comment: string) {
		busy = true;
		error = '';
		try {
			if (editing) await updatePrinter(editing.id, printerBody(name, comment, true));
			else await createPrinter(printerBody(name, comment, false));
			printers = await listPrinters();
			formOpen = false;
		} catch (e) {
			error = apiErrorMessage(e);
		} finally {
			busy = false;
		}
	}

	async function remove() {
		if (!deleting) return;
		busy = true;
		try {
			await deletePrinter(deleting.id);
			printers = await listPrinters();
			deleting = null;
		} catch (e) {
			toasts.error(apiErrorMessage(e));
		} finally {
			busy = false;
		}
	}
</script>

{#if show}
	<section aria-label={ng.settings_printers_tab()}>
		<div class="sec-label">{ng.settings_printers_tab()}</div>
		{#each paragraphs as p, i (i)}<p class="intro">{p}</p>{/each}
		<Card>
			{#if printers.length === 0}
				<div class="empty">{ng.settings_printers_empty()}</div>
			{:else}
				<ul class="list">
					{#each printers as p (p.id)}
						<li class="item">
							<span class="name">{p.name}</span>
							<span class="comment">{p.comment ?? ''}</span>
							<span class="count mono" title={ng.printer_fields_spool_count()}>
								{p.spoolCount ?? 0}
							</span>
							<span class="row-actions">
								<Button
									variant="ghost"
									ariaLabel={`${m['buttons.edit']()}: ${p.name}`}
									title={m['buttons.edit']()}
									onclick={() => openEdit(p)}><Pencil size={14} /></Button
								>
								<Button
									variant="danger-ghost"
									ariaLabel={`${m['buttons.delete']()}: ${p.name}`}
									title={m['buttons.delete']()}
									onclick={() => (deleting = p)}><Trash2 size={14} /></Button
								>
							</span>
						</li>
					{/each}
				</ul>
			{/if}
			<div class="foot">
				<Button variant="outline" onclick={openAdd}>
					<Plus size={14} />
					{ng.settings_printers_add_title()}
				</Button>
			</div>
		</Card>
	</section>

	{#if formOpen}
		<PrinterFormModal
			printer={editing ?? undefined}
			{busy}
			{error}
			onclose={() => (formOpen = false)}
			onsubmit={submit}
		/>
	{/if}

	<ConfirmDialog
		open={deleting !== null}
		{busy}
		title={ng.settings_printers_tab()}
		lines={deleting ? [ng.settings_printers_delete_confirm({ name: deleting.name })] : []}
		confirmLabel={m['buttons.delete']()}
		onconfirm={remove}
		onclose={() => (deleting = null)}
	/>
{/if}

<style>
	.sec-label {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-dim);
		margin: 22px 0 8px;
	}
	.intro {
		margin: 0 0 10px;
		font-size: 12px;
		line-height: 1.55;
		color: var(--text-muted);
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.item {
		display: grid;
		grid-template-columns: minmax(80px, 1fr) minmax(0, 2fr) auto auto;
		align-items: center;
		gap: 12px;
		padding: 10px 14px;
		font-size: 13px;
	}
	.item + .item {
		border-top: 1px solid var(--border);
	}
	.comment {
		color: var(--text-dim);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 12px;
	}
	.count {
		color: var(--text-dim);
		font-size: 12px;
		min-width: 2ch;
		text-align: right;
	}
	.row-actions {
		display: inline-flex;
		gap: 2px;
	}
	.empty {
		padding: 14px;
		font-size: 12.5px;
		color: var(--text-dim);
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		padding: 10px 14px;
		border-top: 1px solid var(--border);
	}
	@media (max-width: 560px) {
		.item {
			grid-template-columns: 1fr auto auto;
		}
		.comment {
			grid-column: 1 / -1;
		}
	}
</style>
