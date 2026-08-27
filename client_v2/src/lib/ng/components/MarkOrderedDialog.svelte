<script lang="ts">
	// US1 "Mark as ordered" dialog (#298) — ported from
	// client/src/pages/orders/markOrderedDialog.tsx: a one-line order for a single low-stock
	// filament, opened from a per-row action on the dashboard tab and the Low Stock page.
	// Shop AutoComplete (creating a shop inline on submit), an order-date/time picker
	// defaulted to now but backdatable, quantity, and optional price/order-number/link.
	//
	// The caller mounts this only while a filament is actually chosen (`{#if
	// markOrderedFilament}<MarkOrderedDialog filament={markOrderedFilament} .../>{/if}`,
	// same as upstream's own comment on why its two order dialogs are conditionally
	// rendered) rather than passing an `open` flag, so there is nothing to reset on
	// open -- every `$state` below already starts at its default each time.
	import Button from '$components/Button.svelte';
	import Field from '$components/Field.svelte';
	import FieldGrid from '$components/FieldGrid.svelte';
	import Combobox from '$components/Combobox.svelte';
	import NumberInput from '$components/NumberInput.svelte';
	import DateTimeField from '$components/DateTimeField.svelte';
	import EditableField from '$components/EditableField.svelte';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { listShops, ensureShop, createOrder } from '$lib/ng/api';
	import { buildMarkOrderedBody } from '$lib/ng/orderBody';
	import { getFilamentName } from '$lib/ng/analytics';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { parseDecimal } from '$lib/utils/numeric';
	import type { ForkFilament } from '$lib/ng/types';
	import type { Vendor } from '$lib/types';

	interface Props {
		filament: ForkFilament;
		vendors: Vendor[];
		onclose: () => void;
		onsuccess: () => void;
	}
	let { filament, vendors, onclose, onsuccess }: Props = $props();

	let shopName = $state('');
	let shops = $state<string[]>([]);
	let orderedAt = $state<string | undefined>(new Date().toISOString());
	// NumberInput's bindable mode always keeps its bound value as a string (see
	// $lib/components/NumberInput.svelte and AddSpoolModal's `price`/`weight` fields for
	// the same convention) -- parsed to an integer at the point of use below.
	let quantity = $state('1');
	let quantityNum = $derived(Math.trunc(parseDecimal(quantity) ?? 0));
	let pricePerUnit = $state<number | undefined>(undefined);
	let orderNumber = $state('');
	let url = $state('');
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
		if (submitting || quantityNum < 1 || !orderedAt) return;
		submitting = true;
		try {
			const name = shopName.trim();
			const shopId = name ? await ensureShop(name) : undefined;
			const body = buildMarkOrderedBody({
				filamentId: filament.id,
				quantity: quantityNum,
				orderedAt,
				shopId,
				pricePerUnit,
				orderNumber: orderNumber.trim() || undefined,
				url: url.trim() || undefined
			});
			await createOrder(body);
			onsuccess();
			onclose();
		} catch (e) {
			// Includes buildMarkOrderedBody's own thrown error for a filament id that can't
			// round-trip as an integer -- surfaced as a toast rather than swallowed, same as
			// any other order-creation failure.
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
		aria-labelledby="mark-ordered-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="mark-ordered-title">
				{ng.orders_mark_ordered_title({ name: getFilamentName(filament, vendors) })}
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
				<Field label={ng.orders_quantity()}>
					<NumberInput bind:value={quantity} min={1} required invalid={quantityNum < 1} />
				</Field>
				<Field label={ng.orders_price_per_unit()}>
					<NumberInput
						value={pricePerUnit ?? ''}
						min={0}
						placeholder="21.90"
						onchange={(v) => (pricePerUnit = v)}
						onclear={() => (pricePerUnit = undefined)}
					/>
				</Field>
				<Field label={ng.orders_order_number_field()}>
					<!-- EditableField (not a bare <input>) so this picks up the Field's
					     aria-labelledby wiring the same way NumberInput/Combobox above do. -->
					<EditableField
						value={orderNumber}
						placeholder="e.g. 3DJ-84302"
						oninput={(v) => (orderNumber = v)}
					/>
				</Field>
				<Field label={ng.orders_url()}>
					<EditableField value={url} placeholder="https://..." linkify oninput={(v) => (url = v)} />
				</Field>
			</FieldGrid>
		</form>

		<div class="foot">
			<Button variant="outline" disabled={submitting} onclick={close}>{m['buttons.cancel']()}</Button>
			<Button variant="primary" disabled={submitting || quantityNum < 1 || !orderedAt} onclick={submit}>
				{ng.orders_mark_ordered()}
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
		width: 480px;
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
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px 16px;
		flex: none;
	}
</style>
