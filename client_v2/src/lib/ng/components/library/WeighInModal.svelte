<script lang="ts">
	/**
	 * Spoolman NG fork addition (#412 step 2): weigh the selected spools one after another.
	 *
	 * Put a spool on the scale, type the reading, Enter, next. Each save is one request to the
	 * endpoint the inspector's Adjust panel uses, with an Idempotency-Key so a retry cannot count
	 * a reading twice (see recordReading), and the mode is shared with
	 * that panel (see ADJUST_MODE_KEY). The order, skipping and failure handling live in
	 * $lib/ng/weighIn, where they are unit-tested.
	 */
	import { untrack } from 'svelte';
	import Button from '$components/Button.svelte';
	import NumberInput from '$components/NumberInput.svelte';
	import NgFormModal from '../NgFormModal.svelte';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { recordReading } from '$lib/ng/api';
	import { inventory } from '$lib/stores/inventory.svelte';
	import { HttpError } from '$lib/api/http';
	import { rowIdentity, type SpoolVM } from '$lib/utils/library';
	import { weightAuto } from '$lib/utils/format';
	import {
		ADJUST_MODE_KEY,
		ADJUST_MODES,
		currentId,
		failed,
		finish,
		isFinished,
		newIdempotencyKey,
		parseAdjustMode,
		parseReading,
		saved,
		skip,
		startWeighIn,
		weighSummary,
		type AdjustMode,
		type WeighStatus
	} from '$lib/ng/weighIn';

	interface Props {
		/** The spools to weigh, in the order to weigh them. */
		spools: SpoolVM[];
		onclose: () => void;
	}
	let { spools, onclose }: Props = $props();

	// The queue is fixed when the weigh-in opens (BulkBar passes a copy of the selection), so
	// the prop is read once, deliberately.
	const queue = untrack(() => spools);
	const byId = new Map(queue.map((vm) => [vm.spool.id, vm]));

	function readMode(): AdjustMode {
		try {
			return parseAdjustMode(localStorage.getItem(ADJUST_MODE_KEY));
		} catch {
			return 'length';
		}
	}

	let weigh = $state(startWeighIn(queue.map((vm) => vm.spool.id)));
	let mode = $state<AdjustMode>(readMode());
	let reading = $state('');
	let error = $state<string | null>(null);
	let busy = $state(false);
	let lastSaved = $state<string | null>(null);
	// One key per spool, kept across retries and replaced only on moving on: a retry after a
	// response that was lost on the way back must not consume the filament twice.
	let attemptKey = newIdempotencyKey();
	let field = $state<HTMLDivElement>();

	let current = $derived.by(() => {
		const id = currentId(weigh);
		return id === null ? null : (byId.get(id) ?? null);
	});
	let identity = $derived(current ? rowIdentity(current, 'flat') : null);
	// The live figure, not the one captured when the spool was ticked: it may have been used or
	// weighed since, and the reading about to be typed is judged against this number.
	let remaining = $derived(
		current ? (inventory.spoolById(current.spool.id)?.remaining ?? current.spool.remaining) : 0
	);
	let summary = $derived(weighSummary(weigh.results));

	const MODE_LABEL: Record<AdjustMode, () => string> = {
		length: m['spool.form.measurementType.length'],
		weight: m['spool.form.measurementType.weight'],
		measured_weight: m['spool.fields.measuredWeight']
	};
	const MODE_UNIT: Record<AdjustMode, string> = { length: 'mm', weight: 'g', measured_weight: 'g' };

	// Each spool starts with an empty field that has the focus, so the next reading can be typed
	// straight away. Keyed on the position, not the value, so a failed save keeps what was typed.
	$effect(() => {
		void weigh.index;
		field?.querySelector('input')?.focus();
	});

	function setMode(next: AdjustMode) {
		mode = next;
		error = null;
		// Back to the reading: the mode is picked once, then every spool is a number and Enter.
		field?.querySelector('input')?.focus();
		try {
			localStorage.setItem(ADJUST_MODE_KEY, next);
		} catch {
			/* remembering the mode is a convenience */
		}
	}

	function name(vm: SpoolVM): string {
		const id = rowIdentity(vm, 'flat');
		return [vm.idLabel, id.title, id.sub].filter(Boolean).join(' ');
	}

	async function save() {
		if (!current || busy) return;
		const parsed = parseReading(reading, mode);
		if ('error' in parsed) {
			error =
				parsed.error === 'length' ? m['inspector.enterValidLength']() : m['inspector.enterValidWeight']();
			return;
		}
		error = null;
		busy = true;
		const vm = current;
		try {
			inventory.upsertSpool(await recordReading(vm.spool.id, mode, parsed.value, attemptKey));
			weigh = saved(weigh);
			attemptKey = newIdempotencyKey();
			reading = '';
			lastSaved = ng.spool_weigh_updated({ name: name(vm) });
		} catch (e) {
			// Stays on this spool with the reading still typed, so a retry is one keypress.
			// The server's own reason when it gave one ("Spool not found."), not the
			// request line HttpError's message leads with.
			const detail = e instanceof HttpError ? e.body?.message : undefined;
			const reason = typeof detail === 'string' ? detail : m['inspector.adjustFailed']();
			weigh = failed(weigh, reason);
			error = reason;
		} finally {
			busy = false;
		}
	}

	function next() {
		weigh = skip(weigh);
		attemptKey = newIdempotencyKey();
		reading = '';
		error = null;
	}

	function stop() {
		weigh = finish(weigh);
		error = null;
	}

	const STATUS_LABEL: Record<WeighStatus, () => string> = {
		updated: ng.spool_weigh_status_updated,
		skipped: ng.spool_weigh_status_skipped,
		failed: ng.spool_weigh_status_failed
	};
</script>

<NgFormModal title={ng.spool_weigh_title()} {busy} {onclose} onsubmit={isFinished(weigh) ? onclose : save}>
	{#if current && identity}
		<div class="head">
			<span class="progress"
				>{ng.spool_weigh_progress({ index: weigh.index + 1, count: weigh.queue.length })}</span
			>
			<span class="who">
				<span class="mono">{current.idLabel}</span>
				{#if identity.title}<span class="title">{identity.title}</span>{/if}
				{#if identity.sub}<span class="sub">{identity.sub}</span>{/if}
			</span>
			<span class="meta">
				{#if current.location}<span>{current.location} · </span>{/if}<span
					>{m['spool.fields.remainingWeight']()}</span
				>
				<span class="mono">{weightAuto(remaining)}</span>
			</span>
		</div>

		<div class="modes" role="group" aria-label={ng.spool_weigh_title()}>
			{#each ADJUST_MODES as key (key)}
				<button
					type="button"
					class="mode"
					class:active={mode === key}
					aria-pressed={mode === key}
					disabled={busy}
					onclick={() => setMode(key)}>{MODE_LABEL[key]()}</button
				>
			{/each}
		</div>

		<div class="fld" bind:this={field}>
			<NumberInput
				bind:value={reading}
				unit={MODE_UNIT[mode]}
				step={0.01}
				disabled={busy}
				invalid={error !== null}
				ariaLabel={mode === 'measured_weight' ? m['inspector.newGross']() : m['inspector.consumeAmount']()}
			/>
			<span class="help"
				>{mode === 'measured_weight' ? m['inspector.measuredHelp']() : m['inspector.adjustHelp']()}</span
			>
		</div>
		{#if error}<div class="error" role="alert">{error}</div>{/if}
		{#if lastSaved}<div class="saved" role="status">{lastSaved}</div>{/if}
	{:else}
		<p class="summary" role="status">
			{ng.spool_weigh_summary({ updated: summary.updated, skipped: summary.skipped, failed: summary.failed })}
		</p>
		{#if weigh.results.length > 0}
			<ul class="results">
				{#each weigh.results as r (r.id)}
					{@const vm = byId.get(r.id)}
					<li class={r.status}>
						<span class="name">{vm ? name(vm) : `#${r.id}`}</span>
						<span class="status"
							>{STATUS_LABEL[r.status]()}{#if r.error}: {r.error}{/if}</span
						>
					</li>
				{/each}
			</ul>
		{/if}
	{/if}

	{#snippet footer()}
		{#if isFinished(weigh)}
			<Button variant="primary" type="submit">{m['buttons.close']()}</Button>
		{:else}
			<Button variant="ghost" disabled={busy} onclick={stop}>{ng.spool_weigh_done()}</Button>
			<Button variant="outline" disabled={busy} onclick={next}>{ng.spool_weigh_skip()}</Button>
			<Button variant="primary" type="submit" disabled={busy}>{ng.spool_weigh_save_next()}</Button>
		{/if}
	{/snippet}
</NgFormModal>

<style>
	.head {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.progress {
		font-size: 11px;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.who {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 6px;
	}
	.title {
		font-weight: 600;
	}
	.sub,
	.meta {
		font-size: 12px;
		color: var(--text-dim);
	}
	.modes {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}
	.mode {
		padding: 4px 9px;
		font-size: 12px;
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		background: var(--bg-subtle);
		color: var(--text-muted);
		cursor: pointer;
	}
	.mode.active {
		background: var(--accent-wash);
		border-color: var(--accent-border);
		color: var(--accent-soft);
	}
	.saved {
		font-size: 12px;
		color: var(--text-dim);
	}
	.summary {
		margin: 0;
		font-weight: 600;
	}
	.results {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
		max-height: 40vh;
		overflow-y: auto;
		font-size: 12.5px;
	}
	.results li {
		display: flex;
		justify-content: space-between;
		gap: 12px;
	}
	.results .name {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.results .status {
		flex: none;
		color: var(--text-dim);
	}
	.results li.failed .status {
		color: var(--danger-soft);
	}
</style>
