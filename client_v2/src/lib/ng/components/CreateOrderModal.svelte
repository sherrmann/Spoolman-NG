<script lang="ts">
	// US2 bulk create-order modal (#298) — ported from
	// client/src/pages/orders/createOrderModal.tsx: opened from the Low Stock page's
	// multi-select. Builds one order with one line per selected filament
	// (buildBulkOrderBody) -- quantities default to 1 and are editable per row before
	// save. Shop picker and order-date/time field mirror the US1 single-line dialog
	// (MarkOrderedDialog.svelte).
	//
	// Same conditionally-mounted-only-while-open convention as MarkOrderedDialog: the
	// caller renders this behind `{#if bulkOpen}...{/if}`, so `quantities` below only
	// ever needs to be seeded once, from the `rows` this was opened with.
	import { untrack } from 'svelte';
	import Button from '$components/Button.svelte';
	import Field from '$components/Field.svelte';
	import FieldGrid from '$components/FieldGrid.svelte';
	import Combobox from '$components/Combobox.svelte';
	import NumberInput from '$components/NumberInput.svelte';
	import DateTimeField from '$components/DateTimeField.svelte';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { listShops, ensureShop, createOrder } from '$lib/ng/api';
	import { buildBulkOrderBody, type OrderLineInput } from '$lib/ng/orderBody';
	import { getFilamentName, type LowStockRow } from '$lib/ng/analytics';
	import { toasts } from '$lib/stores/toasts.svelte';
	import type { Vendor } from '$lib/types';

	interface Props {
		rows: LowStockRow[];
		vendors: Vendor[];
		onclose: () => void;
		onsuccess: () => void;
	}
	let { rows, vendors, onclose, onsuccess }: Props = $props();

	let shopName = $state('');
	let shops = $state<string[]>([]);
	let orderedAt = $state<string | undefined>(new Date().toISOString());
	// Keyed by filament id, seeded once from the rows this modal opened with. `rows`
	// itself stays a live prop (so remaining/threshold shown in the table below track a
	// background reload while this is open) but this map is deliberately NOT re-derived
	// from it, so a live reload can't wipe a quantity the user already typed.
	let quantities = $state<Record<string, string>>(
		Object.fromEntries(untrack(() => rows).map((r) => [r.filament.id, '1']))
	);
	let submitting = $state(false);

	let dialog = $state<HTMLDivElement>();
	let opener: HTMLElement | null = null;
	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		dialog?.focus();
		listShops()
			.then((s) => (shops = s.map((sh) => sh.name)))
			.catch(() => (shops = []));
		return () => opener?.focus();
	});

	function close() {
		if (!submitting) onclose();
	}

	async function submit() {
		if (submitting || !orderedAt || rows.length === 0) return;
		submitting = true;
		try {
			const name = shopName.trim();
			const shopId = name ? await ensureShop(name) : undefined;
			const lines: OrderLineInput[] = rows.map((r) => ({
				filamentId: r.filament.id,
				quantity: Math.max(1, Math.trunc(Number(quantities[r.filament.id]) || 1))
			}));
			const body = buildBulkOrderBody(lines, orderedAt, shopId);
			await createOrder(body);
			onsuccess();
			onclose();
		} catch (e) {
			// Includes buildBulkOrderBody's own thrown error for a filament id that can't
			// round-trip as an integer -- surfaced as a toast rather than swallowed.
			console.error('Failed to create order', e);
			toasts.error(ng.orders_create_error());
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape') close();
	}}
/>

<div class="overlay">
	<!-- Click-outside catcher: a sibling of the dialog, not a parent, so it doesn't nest
	     interactive controls inside an interactive element. -->
	<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={close}></button>
	<div
		class="modal"
		role="dialog"
		aria-modal="true"
		aria-labelledby="create-order-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="create-order-title">
				{ng.orders_create_order_title({ count: rows.length })}
			</span>
			<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
		</div>

		<form
			class="body"
			onsubmit={(e) => {
				e.preventDefault();
				submit();
			}}
		>
			<FieldGrid labelWidth="140px">
				<Field label={ng.orders_shop()}>
					<Combobox
						value={shopName}
						options={shops}
						placeholder={ng.orders_shop_placeholder()}
						oninput={(v) => (shopName = v)}
					/>
				</Field>
				<Field label={ng.orders_order_date()}>
					<DateTimeField value={orderedAt} oninput={(iso) => (orderedAt = iso)} />
				</Field>
			</FieldGrid>

			<div class="order-table">
				<div class="order-table-row order-table-head">
					<span>{ng.spool_fields_filament()}</span>
					<span>{ng.orders_quantity()}</span>
				</div>
				{#each rows as row (row.filament.id)}
					<div class="order-table-row">
						<span class="fname">{getFilamentName(row.filament, vendors)}</span>
						<NumberInput
							bind:value={quantities[row.filament.id]}
							min={1}
							width="90px"
							ariaLabel={`${ng.orders_quantity()} — ${getFilamentName(row.filament, vendors)}`}
						/>
					</div>
				{/each}
			</div>
		</form>

		<div class="foot">
			<Button variant="outline" disabled={submitting} onclick={close}>{m['buttons.cancel']()}</Button>
			<Button variant="primary" disabled={submitting || !orderedAt || rows.length === 0} onclick={submit}>
				{ng.orders_create_order()}
			</Button>
		</div>
	</div>
</div>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		z-index: 60;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding: 8vh 16px 16px;
	}
	.backdrop {
		position: fixed;
		inset: 0;
		border: none;
		margin: 0;
		padding: 0;
		background: transparent;
		cursor: default;
	}
	.modal {
		position: relative;
		z-index: 1;
		width: 560px;
		max-width: 100%;
		max-height: 84vh;
		display: flex;
		flex-direction: column;
		background: var(--bg);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-xl);
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
		overflow: hidden;
	}
	.modal-head {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 16px 20px 0;
		flex: none;
	}
	.title {
		font-weight: 700;
		font-size: 15px;
	}
	.x {
		margin-left: auto;
		color: var(--text-dim);
		cursor: pointer;
		padding: 4px 8px;
		background: none;
		border: none;
		display: inline-flex;
	}
	.x:hover {
		color: var(--text);
	}
	.body {
		padding: 14px 20px 4px;
		overflow-y: auto;
	}
	.order-table {
		margin-top: 18px;
		border: 1px solid var(--border);
		border-radius: var(--radius-md);
		overflow: hidden;
	}
	.order-table-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 8px 12px;
		border-top: 1px solid var(--hairline);
		font-size: 12.5px;
	}
	.order-table-row:first-child {
		border-top: none;
	}
	.order-table-head {
		font-size: 10.5px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-faint);
		background: var(--surface-2);
	}
	.order-table-head span:last-child {
		flex: none;
		width: 90px;
		text-align: left;
	}
	.fname {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		flex: 1;
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px 16px;
		flex: none;
	}
</style>
