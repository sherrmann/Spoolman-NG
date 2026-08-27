<script lang="ts">
	// Order details/edit modal (#298) — ported from client/src/pages/orders/orderDetailsModal.tsx:
	// opened by clicking an order row on the Orders list (routes/orders/+page.svelte). Shows the
	// shop, ordered date, order number, url and comment, all editable via the same
	// Combobox/DateTimeField/EditableField pattern as MarkOrderedDialog.svelte. Each line's quantity
	// and price/spool are editable while still outstanding; already-arrived lines render read-only
	// with their arrived state. Saving PATCHes /order/{id}: since the backend fully replaces the
	// line set whenever `lines` is present (see orderEditBody.ts's docstring), every line is sent
	// back — buildEditedLines folds the per-row edits over the order's original lines so arrived
	// ones go out unchanged. Delete removes the order (and cascades its lines) after a confirm,
	// matching FilamentInspector's delete-confirm pattern.
	//
	// The caller mounts this only while an order is actually selected (`{#if detailsOrder}<OrderDetailsModal
	// order={detailsOrder} .../>{/if}`), same as MarkOrderedDialog's own doc comment on why upstream's
	// two order dialogs are conditionally rendered — so every `$state` below is seeded once, from the
	// order this opened with, and there is nothing to reset on a later reopen.
	import { untrack } from 'svelte';
	import Button from '$components/Button.svelte';
	import Field from '$components/Field.svelte';
	import FieldGrid from '$components/FieldGrid.svelte';
	import Combobox from '$components/Combobox.svelte';
	import NumberInput from '$components/NumberInput.svelte';
	import { parseDecimal } from '$lib/utils/numeric';
	import DateTimeField from '$components/DateTimeField.svelte';
	import EditableField from '$components/EditableField.svelte';
	import ConfirmDialog from '$components/ConfirmDialog.svelte';
	import X from '@lucide/svelte/icons/x';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { listShops, ensureShop, updateOrder, deleteOrder } from '$lib/ng/api';
	import { buildEditedLines, buildOrderPatchBody, type LineEdit } from '$lib/ng/orderEditBody';
	import { getFilamentName } from '$lib/ng/analytics';
	import { toasts } from '$lib/stores/toasts.svelte';
	import type { ForkFilament, Order } from '$lib/ng/types';
	import type { Vendor } from '$lib/types';

	interface Props {
		order: Order;
		filaments: ForkFilament[];
		vendors: Vendor[];
		onclose: () => void;
		onsuccess: () => void;
	}
	let { order, filaments, vendors, onclose, onsuccess }: Props = $props();

	// This dialog is only ever mounted fresh for one order (see the module doc comment above), so
	// `order` never changes out from under it — but reading a prop directly in a `$state`
	// initializer still trips Svelte's "state_referenced_locally" check, since in general nothing
	// stops a prop from changing later. `untrack` says that's fine here, the same way
	// CreateOrderModal.svelte's `untrack(() => rows)` does for its own once-only seeding.
	const initial = untrack(() => order);

	let shopName = $state(initial.shop?.name ?? '');
	let shops = $state<string[]>([]);
	let orderedAt = $state<string | undefined>(initial.orderedAt);
	let orderNumber = $state(initial.orderNumber ?? '');
	let url = $state(initial.url ?? '');
	let comment = $state(initial.comment ?? '');
	// Seeded from the still-outstanding lines only — an arrived line is never edited (see
	// buildEditedLines, which passes those through untouched regardless of what's in here).
	//
	// Held as strings and bound live (NumberInput's default mode) rather than as numbers
	// committed on blur. Both work; this way the state here is the single source of truth for
	// what the field shows, so there is no window in which the input holds a value the component
	// has not seen yet.
	let lineDrafts = $state<Record<number, { quantity: string; pricePerUnit: string }>>(
		Object.fromEntries(
			initial.lines
				.filter((l) => !l.arrivedAt)
				.map((l) => [
					l.id,
					{
						quantity: String(l.quantity),
						pricePerUnit: l.pricePerUnit == null ? '' : String(l.pricePerUnit)
					}
				])
		)
	);
	let submitting = $state(false);
	let confirmDeleteOpen = $state(false);
	let deleting = $state(false);

	const orderLabel = initial.orderNumber ?? `#${initial.id}`;

	/** The drafts, parsed back into the numbers buildEditedLines expects. */
	function editsFromDrafts(): Record<number, LineEdit> {
		return Object.fromEntries(
			Object.entries(lineDrafts).map(([id, d]) => {
				const quantity = parseDecimal(d.quantity);
				const price = parseDecimal(d.pricePerUnit);
				return [
					Number(id),
					{
						// A blank or unparseable quantity keeps the line rather than deleting it: 1 is
						// the smallest the API accepts, and silently dropping a line here would be a
						// destructive reading of a typo.
						quantity: quantity == null || quantity < 1 ? 1 : quantity,
						pricePerUnit: price == null ? undefined : price
					}
				];
			})
		);
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
		if (!submitting && !deleting) onclose();
	}

	async function submit() {
		if (submitting || !orderedAt) return;
		submitting = true;
		try {
			const name = shopName.trim();
			const shopId = name ? await ensureShop(name) : null;
			const lines = buildEditedLines(order.lines, editsFromDrafts());
			const body = buildOrderPatchBody({ shopId, orderedAt, orderNumber, url, comment }, lines);
			await updateOrder(order.id, body);
			onsuccess();
			onclose();
		} catch (e) {
			console.error('Failed to update order', e);
			toasts.error(ng.orders_update_error());
		} finally {
			submitting = false;
		}
	}

	async function confirmDelete() {
		deleting = true;
		try {
			await deleteOrder(order.id);
			onsuccess();
			onclose();
		} catch (e) {
			console.error('Failed to delete order', e);
			toasts.error(ng.orders_delete_error());
			confirmDeleteOpen = false;
		} finally {
			deleting = false;
		}
	}
</script>

<svelte:window
	onkeydown={(e) => {
		// Ignored while the delete confirm is open: both dialogs listen on `window`, and
		// stopPropagation() in ConfirmDialog wouldn't stop this sibling listener from also
		// firing (it only prevents bubbling past the target, not other listeners on it) — so
		// this guard is what keeps Escape from closing both at once.
		if (e.key === 'Escape' && !confirmDeleteOpen) close();
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
		aria-labelledby="order-details-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="order-details-title">
				{ng.orders_details_title({ number: orderLabel })}
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
				{#each order.lines as line (line.id)}
					{@const filament = filaments.find((f) => f.id === line.filamentId)}
					{@const name = filament ? getFilamentName(filament, vendors) : `#${line.filamentId}`}
					{#if line.arrivedAt}
						<div class="line arrived">
							<span class="line-name">{name}</span>
							<span class="line-qty">× {line.quantity}</span>
							<span class="line-price">{line.pricePerUnit != null ? line.pricePerUnit : '—'}</span>
							<span class="line-state check">✓ {ng.orders_state_arrived()}</span>
						</div>
					{:else}
						<div class="line">
							<span class="line-name">{name}</span>
							<NumberInput
								bind:value={lineDrafts[line.id].quantity}
								min={1}
								width="80px"
								ariaLabel={`${ng.orders_quantity()} — ${name}`}
							/>
							<NumberInput
								bind:value={lineDrafts[line.id].pricePerUnit}
								min={0}
								width="100px"
								placeholder="21.90"
								ariaLabel={`${ng.orders_price_per_unit()} — ${name}`}
							/>
							<span class="line-state">{ng.orders_outstanding()}</span>
						</div>
					{/if}
				{/each}
			</div>
		</form>

		<div class="foot">
			<Button
				variant="danger-ghost"
				disabled={submitting || deleting}
				onclick={() => (confirmDeleteOpen = true)}
			>
				<Trash2 size={14} />
				{m['buttons.delete']()}
			</Button>
			<span class="spacer"></span>
			<Button variant="outline" disabled={submitting || deleting} onclick={close}>
				{m['buttons.cancel']()}
			</Button>
			<Button variant="primary" disabled={submitting || deleting || !orderedAt} onclick={submit}>
				{m['buttons.save']()}
			</Button>
		</div>
	</div>
</div>

<ConfirmDialog
	open={confirmDeleteOpen}
	busy={deleting}
	title={orderLabel}
	lines={[ng.orders_delete_confirm()]}
	confirmLabel={m['buttons.delete']()}
	onconfirm={confirmDelete}
	onclose={() => (confirmDeleteOpen = false)}
/>

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
		gap: 10px;
		flex-wrap: wrap;
		padding: 6px 0;
		border-top: 1px solid var(--hairline);
	}
	.line:first-child {
		border-top: none;
	}
	.line.arrived {
		opacity: 0.55;
	}
	.line-name {
		flex: 1 1 auto;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 12.5px;
	}
	.line-qty,
	.line-price {
		font-size: 12.5px;
		color: var(--text-dim);
		white-space: nowrap;
	}
	.line-state {
		white-space: nowrap;
		font-size: 11.5px;
		color: var(--text-faint);
	}
	.line-state.check {
		color: var(--success);
	}
	.foot {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 14px 20px 16px;
		flex: none;
	}
	.spacer {
		flex: 1;
	}
</style>
