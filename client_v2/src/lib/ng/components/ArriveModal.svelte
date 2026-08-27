<script lang="ts">
	// US3 split-arrival dialog (#298) — ported from client/src/pages/orders/arriveModal.tsx: a row
	// per order line — a checkbox, the filament name, and (for still-outstanding lines) a quantity
	// input defaulting to the full outstanding count, with a live "N of M outstanding" label and a
	// split preview once the delivered amount is lowered. Already-arrived lines render disabled with
	// a ✓. `create_spools` (default on) and an optional location sit below the list; submit POSTs
	// `buildArriveBody`'s output (ported to $lib/ng/arriveBody, pure and unit-tested there) to
	// /order/{id}/arrive.
	//
	// Unlike the React original — which can also be opened from a spool-create "on order" banner
	// with only an order id, and so fetches the order/filament/location lists itself — this fork has
	// no such banner yet, so the caller (routes/orders/+page.svelte) always has the full `order` (and
	// its already-loaded `filaments`/`vendors`) in hand and passes them down directly; only
	// `locations` is fetched here, since nothing else on the Orders page needs it.
	//
	// Mounted only while an order is actually being arrived (same conditionally-mounted convention
	// as MarkOrderedDialog), so every `$state` below is seeded once, from the order this opened with.
	import { untrack } from 'svelte';
	import Button from '$components/Button.svelte';
	import NumberInput from '$components/NumberInput.svelte';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { arriveOrder, listLocations } from '$lib/ng/api';
	import { buildArriveBody, type ArriveLineInput } from '$lib/ng/arriveBody';
	import { getFilamentName } from '$lib/ng/analytics';
	import { toasts } from '$lib/stores/toasts.svelte';
	import type { ForkFilament, Order, Location } from '$lib/ng/types';
	import type { Vendor } from '$lib/types';

	interface Props {
		order: Order;
		filaments: ForkFilament[];
		vendors: Vendor[];
		onclose: () => void;
		onsuccess: () => void;
	}
	let { order, filaments, vendors, onclose, onsuccess }: Props = $props();

	interface RowState {
		selected: boolean;
		quantity: number;
	}

	// This dialog is only ever mounted fresh for one order (see the module doc comment above), so
	// `order` never changes out from under it — `untrack` here is the same once-only-seeding
	// convention as CreateOrderModal.svelte's `untrack(() => rows)`.
	const initial = untrack(() => order);

	// Seeded once from the outstanding lines: every line starts fully selected at its full
	// outstanding quantity, matching the React original's default (a delivery is assumed complete
	// until the user says otherwise).
	let rows = $state<Record<number, RowState>>(
		Object.fromEntries(
			initial.lines.filter((l) => !l.arrivedAt).map((l) => [l.id, { selected: true, quantity: l.quantity }])
		)
	);
	let createSpools = $state(true);
	let locationId = $state<number | undefined>(undefined);
	let locations = $state<Location[]>([]);
	let submitting = $state(false);

	const orderLabel = initial.orderNumber ?? `${initial.id}`;

	let dialog = $state<HTMLDivElement>();
	let opener: HTMLElement | null = null;
	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		dialog?.focus();
		listLocations()
			.then((l) => (locations = l))
			.catch(() => (locations = []));
		return () => opener?.focus();
	});

	function close() {
		if (!submitting) onclose();
	}

	let lineInputs = $derived(
		order.lines
			.filter((l) => !l.arrivedAt)
			.map((l): ArriveLineInput => ({
				lineId: l.id,
				quantity: rows[l.id]?.quantity ?? l.quantity,
				outstanding: l.quantity,
				selected: rows[l.id]?.selected ?? true
			}))
	);
	let canSubmit = $derived(lineInputs.some((l) => l.selected && l.quantity > 0));

	async function submit() {
		if (submitting || !canSubmit) return;
		submitting = true;
		try {
			const body = buildArriveBody(lineInputs, createSpools, locationId);
			await arriveOrder(order.id, body);
			onsuccess();
			onclose();
		} catch (e) {
			console.error('Failed to mark order arrived', e);
			toasts.error(ng.orders_arrive_error());
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
		aria-labelledby="arrive-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="arrive-title">{ng.orders_arrive_title({ number: orderLabel })}</span>
			<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
		</div>

		<div class="body">
			<p class="subtitle">{ng.orders_arrive_subtitle()}</p>
			<div class="lines">
				{#each order.lines as line (line.id)}
					{@const filament = filaments.find((f) => f.id === line.filamentId)}
					{@const name = filament ? getFilamentName(filament, vendors) : `#${line.filamentId}`}
					{#if line.arrivedAt}
						<div class="line disabled">
							<input type="checkbox" checked disabled aria-label={name} />
							<span class="line-name">{name}</span>
							<span class="line-check">✓ {ng.orders_arrived_check()}</span>
						</div>
					{:else}
						{@const row = rows[line.id] ?? { selected: true, quantity: line.quantity }}
						{@const outstanding = line.quantity}
						<div class="line">
							<input
								type="checkbox"
								checked={row.selected}
								aria-label={name}
								onchange={(e) =>
									(rows = { ...rows, [line.id]: { ...row, selected: e.currentTarget.checked } })}
							/>
							<span class="line-name">{name}</span>
							<NumberInput
								value={row.quantity}
								min={1}
								max={outstanding}
								width="80px"
								disabled={!row.selected}
								ariaLabel={`${ng.orders_quantity()} — ${name}`}
								onchange={(v) => (rows = { ...rows, [line.id]: { ...row, quantity: v } })}
							/>
							<span class="line-outstanding">
								{ng.orders_n_of_m({ delivered: row.quantity, outstanding })}
							</span>
							{#if row.selected && row.quantity < outstanding}
								<div class="split-preview">
									{ng.orders_split_preview({ delivered: row.quantity, rest: outstanding - row.quantity })}
								</div>
							{/if}
						</div>
					{/if}
				{/each}
			</div>

			<label class="create-spools">
				<input type="checkbox" bind:checked={createSpools} />
				{ng.orders_create_spools()}
			</label>

			<label class="location">
				<span>{ng.orders_location()}</span>
				<select
					class="sel"
					value={locationId ?? ''}
					onchange={(e) => (locationId = e.currentTarget.value ? Number(e.currentTarget.value) : undefined)}
				>
					<option value="">—</option>
					{#each locations as loc (loc.id)}
						<option value={loc.id}>{loc.name}</option>
					{/each}
				</select>
			</label>
		</div>

		<div class="foot">
			<Button variant="outline" disabled={submitting} onclick={close}>{m['buttons.cancel']()}</Button>
			<Button variant="primary" disabled={submitting || !canSubmit} onclick={submit}>
				{ng.orders_mark_arrived()}
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
		width: 520px;
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
	.subtitle {
		margin: 0 0 12px;
		font-size: 12.5px;
		color: var(--text-dim);
	}
	.lines {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.line {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}
	.line input[type='checkbox'] {
		accent-color: var(--accent);
	}
	.line.disabled {
		opacity: 0.55;
	}
	.line-name {
		flex: 1 1 auto;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 13px;
	}
	.line-check {
		color: var(--success);
		font-size: 12.5px;
		white-space: nowrap;
	}
	.line-outstanding {
		font-size: 11.5px;
		color: var(--text-faint);
		white-space: nowrap;
	}
	.split-preview {
		flex: 1 0 100%;
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.create-spools {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 16px 0 12px;
		font-size: 13px;
		cursor: pointer;
	}
	.create-spools input {
		accent-color: var(--accent);
	}
	.location {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-bottom: 8px;
		font-size: 12.5px;
		color: var(--text-2);
	}
	.sel {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 7px 8px;
		font-size: 13px;
		width: 100%;
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px 16px;
		flex: none;
	}
</style>
