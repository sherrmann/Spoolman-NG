<script lang="ts">
	// From-scratch "New order" builder (#324) — ported from client/src/pages/orders/newOrderModal.tsx:
	// opened by the Orders page's "+ New order" button. Mirrors the order details/edit modal's header
	// surface (shop Combobox, order-date field, order number, url, comment) but, since there is no
	// existing order to seed lines from, adds a filament picker + lines editor: each line chooses a
	// filament and its quantity/price, with add/remove. On save a POST /order is built by
	// `buildNewOrderBody` (create semantics — blank optional fields omitted, unlike the edit modal's
	// PATCH which sends explicit nulls; see orderEditBody.ts's docstring for why those differ).
	//
	// This client has no generic id-keyed searchable-select component (Combobox only round-trips a
	// plain string value against a string option list, which fits a shop *name* but not a filament
	// *id*), so the picker below is a plain `<select>` — the same widget already used for a
	// small enum choice (ExtraFieldInput.svelte's `.sel`) and for ArriveModal's location picker.
	// It loses the antd original's inline colour swatch per option (native `<option>` can't render
	// arbitrary markup) but keeps the actual feature: choosing a filament by name, sorted the same way.
	//
	// Mounted only while actually open (`{#if creating}<NewOrderModal .../>{/if}`), same
	// conditionally-mounted convention as MarkOrderedDialog/CreateOrderModal — so every `$state`
	// below starts fresh each time and there is nothing to reset on reopen.
	import Button from '$components/Button.svelte';
	import Field from '$components/Field.svelte';
	import FieldGrid from '$components/FieldGrid.svelte';
	import Combobox from '$components/Combobox.svelte';
	import NumberInput from '$components/NumberInput.svelte';
	import DateTimeField from '$components/DateTimeField.svelte';
	import EditableField from '$components/EditableField.svelte';
	import X from '@lucide/svelte/icons/x';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { listShops, ensureShop, createOrder } from '$lib/ng/api';
	import { buildNewOrderBody, type OrderLineInput } from '$lib/ng/orderBody';
	import { getFilamentName } from '$lib/ng/analytics';
	import { toasts } from '$lib/stores/toasts.svelte';
	import type { ForkFilament } from '$lib/ng/types';
	import type { Vendor } from '$lib/types';

	interface Props {
		filaments: ForkFilament[];
		vendors: Vendor[];
		onclose: () => void;
		onsuccess: () => void;
	}
	let { filaments, vendors, onclose, onsuccess }: Props = $props();

	// A draft line in the builder. `key` is a stable identity for #each/edit tracking; `filamentId`
	// is undefined until the user picks one (an incomplete line is dropped on save). Quantity/price
	// are plain numbers, updated via `updateLine` — the same NumberInput "commit" mode
	// (value+onchange, see NumberInput.svelte's own doc comment) OrderDetailsModal/ArriveModal use
	// for their own per-line quantity fields.
	interface DraftLine {
		key: number;
		filamentId?: string;
		quantity: number;
		pricePerUnit?: number;
	}

	let shopName = $state('');
	let shops = $state<string[]>([]);
	let orderedAt = $state<string | undefined>(new Date().toISOString());
	let orderNumber = $state('');
	let url = $state('');
	let comment = $state('');
	let lines = $state<DraftLine[]>([{ key: 0, quantity: 1 }]);
	let nextKey = 1;
	let submitting = $state(false);

	// A $derived, not a one-time snapshot: unlike the dialog's own header/lines state, there's no
	// reason to freeze this against a live filament rename while the picker is open.
	let filamentOptions = $derived(
		[...filaments]
			.map((f) => ({ id: f.id, label: getFilamentName(f, vendors) }))
			.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }))
	);

	// An order needs at least one line with a filament actually chosen; the submit button gates on this.
	let hasValidLine = $derived(lines.some((l) => l.filamentId != null));

	function addLine() {
		lines = [...lines, { key: nextKey++, quantity: 1 }];
	}
	function removeLine(key: number) {
		lines = lines.filter((l) => l.key !== key);
	}
	function updateLine(key: number, patch: Partial<DraftLine>) {
		lines = lines.map((l) => (l.key === key ? { ...l, ...patch } : l));
	}

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
		if (submitting || !orderedAt) return;
		const orderLines: OrderLineInput[] = lines
			.filter((l): l is DraftLine & { filamentId: string } => l.filamentId != null)
			.map((l) => ({ filamentId: l.filamentId, quantity: l.quantity, pricePerUnit: l.pricePerUnit }));
		if (orderLines.length === 0) {
			toasts.error(ng.orders_no_lines());
			return;
		}
		submitting = true;
		try {
			const name = shopName.trim();
			const shopId = name ? await ensureShop(name) : undefined;
			const body = buildNewOrderBody({
				orderedAt,
				lines: orderLines,
				shopId,
				orderNumber: orderNumber.trim() || undefined,
				url: url.trim() || undefined,
				comment: comment.trim() || undefined
			});
			await createOrder(body);
			onsuccess();
			onclose();
		} catch (e) {
			// Includes buildNewOrderBody's own thrown error for a filament id that can't round-trip
			// as an integer -- surfaced as a toast rather than swallowed.
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
		aria-labelledby="new-order-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="new-order-title">{ng.orders_new_order_title()}</span>
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
				<Field label={ng.orders_order_number_field()}>
					<EditableField
						value={orderNumber}
						placeholder="e.g. 3DJ-84302"
						oninput={(v) => (orderNumber = v)}
					/>
				</Field>
				<Field label={ng.orders_url()}>
					<EditableField value={url} placeholder="https://..." linkify oninput={(v) => (url = v)} />
				</Field>
				<Field label={ng.orders_comment()}>
					<textarea class="comment" rows="2" bind:value={comment}></textarea>
				</Field>
			</FieldGrid>

			<div class="lines">
				<div class="lines-header">{ng.orders_lines_summary_title()}</div>
				{#each lines as line (line.key)}
					<div class="line">
						<select
							class="sel filament-select"
							value={line.filamentId ?? ''}
							aria-label={ng.orders_select_filament()}
							onchange={(e) => updateLine(line.key, { filamentId: e.currentTarget.value || undefined })}
						>
							<option value="">{ng.orders_select_filament()}</option>
							{#each filamentOptions as opt (opt.id)}
								<option value={opt.id}>{opt.label}</option>
							{/each}
						</select>
						<NumberInput
							value={line.quantity}
							min={1}
							width="80px"
							ariaLabel={ng.orders_quantity()}
							onchange={(v) => updateLine(line.key, { quantity: v })}
						/>
						<NumberInput
							value={line.pricePerUnit ?? ''}
							min={0}
							width="100px"
							placeholder="21.90"
							ariaLabel={ng.orders_price_per_unit()}
							onchange={(v) => updateLine(line.key, { pricePerUnit: v })}
							onclear={() => updateLine(line.key, { pricePerUnit: undefined })}
						/>
						<Button variant="ghost" ariaLabel={ng.orders_remove_line()} onclick={() => removeLine(line.key)}>
							<Trash2 size={14} />
						</Button>
					</div>
				{/each}
				<Button variant="outline" onclick={addLine}>
					<Plus size={14} />
					{ng.orders_add_line()}
				</Button>
			</div>
		</form>

		<div class="foot">
			<Button variant="outline" disabled={submitting} onclick={close}>{m['buttons.cancel']()}</Button>
			<Button variant="primary" disabled={submitting || !orderedAt || !hasValidLine} onclick={submit}>
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
		width: 640px;
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
	.comment {
		width: 100%;
		border: 1px solid var(--border-strong);
		background: none;
		border-radius: 7px;
		padding: 9px 12px;
		color: var(--text);
		font-size: 13px;
		font-family: inherit;
		resize: vertical;
	}
	.comment:focus {
		outline: none;
		border-color: var(--accent);
	}
	.lines {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-top: 18px;
	}
	.lines-header {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-faint);
	}
	.line {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.filament-select {
		flex: 1 1 200px;
		min-width: 0;
	}
	.sel {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 8px 8px;
		font-size: 13px;
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px 16px;
		flex: none;
	}
</style>
