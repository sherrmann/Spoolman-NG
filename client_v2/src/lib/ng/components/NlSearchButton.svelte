<script lang="ts">
	/**
	 * Search the Library by describing what you want, rather than by picking chips.
	 *
	 * The server translates and GROUNDS: every value it returns has been checked against what is
	 * actually in the database, so a material the model invented is dropped before it reaches
	 * here. The result is applied as ordinary, editable filter chips -- this never becomes a
	 * separate "AI search mode" the user has to leave. That is the whole design: the assistant
	 * fills the existing controls in, and everything after that works the way it always did.
	 *
	 * What it cannot express, it says. This client's Library has no free-text list parameter and
	 * no colour filter, so parts of a translated search can have nowhere to go; planNlSearch
	 * returns those and they are reported rather than dropped. A search that arrives half
	 * applied and silent looks like a bad match, and the user has no way to tell the difference.
	 */
	import Button from '$components/Button.svelte';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { getLocale } from '$lib/paraglide/runtime';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { nlSearchEnabled, nlSearch } from '$lib/ng/aiApi';
	import { planNlSearch, type UnappliedPart } from '$lib/ng/nlSearch';
	import { replaceFilters } from '$lib/library/params';

	let enabled = $state(false);
	let open = $state(false);
	let query = $state('');
	let busy = $state(false);
	let error = $state(false);
	let input = $state<HTMLInputElement | null>(null);

	$effect(() => {
		const controller = new AbortController();
		nlSearchEnabled(controller.signal)
			.then((on) => (enabled = on))
			.catch(() => (enabled = false));
		return () => controller.abort();
	});

	// Focus on open rather than on mount: the field does not exist until then.
	$effect(() => {
		if (open) input?.focus();
	});

	function unappliedText(part: UnappliedPart): string {
		switch (part) {
			case 'search':
				return ng.spool_nlSearch_unapplied_search();
			case 'color':
				return ng.spool_nlSearch_unapplied_color();
			default:
				return ng.spool_nlSearch_unapplied_sort();
		}
	}

	async function run() {
		const text = query.trim();
		if (!text || busy) return;
		busy = true;
		error = false;
		try {
			const plan = planNlSearch(await nlSearch(text, getLocale()));
			replaceFilters(
				plan.filters,
				plan.sortKey ? { key: plan.sortKey, asc: plan.sortAsc ?? true } : undefined
			);
			open = false;
			query = '';

			// Say what happened. "No filters" is the outcome most likely to be mistaken for a
			// broken feature, so it gets said plainly rather than left as an empty list.
			if (plan.filters.length === 0) toasts.info(ng.spool_nlSearch_applied_none());
			else toasts.success(ng.spool_nlSearch_applied({ count: plan.filters.length }));
			for (const part of plan.unapplied) toasts.info(unappliedText(part));
		} catch {
			// Kept open on failure, with the message inline: the user's text is still in the box
			// and retrying is one click. A toast plus a closed popover would lose what they typed.
			error = true;
		} finally {
			busy = false;
		}
	}
</script>

{#if enabled}
	<div class="wrap">
		<button
			class="trigger"
			class:active={open}
			onclick={() => (open = !open)}
			aria-expanded={open}
			title={ng.spool_nlSearch_title()}
			aria-label={ng.spool_nlSearch_title()}
		>
			<Sparkles size={14} />
			{ng.spool_nlSearch_button()}
		</button>

		{#if open}
			<div class="panel" role="dialog" aria-label={ng.spool_nlSearch_title()}>
				<div class="panel-head">
					<span class="panel-title">{ng.spool_nlSearch_title()}</span>
					<button class="x" onclick={() => (open = false)} aria-label={m['buttons.close']()}>
						<X size={14} />
					</button>
				</div>
				<form
					onsubmit={(e) => {
						e.preventDefault();
						run();
					}}
				>
					<input
						class="in"
						bind:this={input}
						bind:value={query}
						placeholder={ng.spool_nlSearch_placeholder()}
						disabled={busy}
						aria-label={ng.spool_nlSearch_title()}
					/>
					<div class="foot">
						<span class="hint">{ng.spool_nlSearch_hint()}</span>
						<Button variant="primary" type="submit" disabled={busy || !query.trim()}>
							{ng.spool_nlSearch_search()}
						</Button>
					</div>
				</form>
				{#if error}
					<p class="err" role="alert">{ng.spool_nlSearch_error()}</p>
				{/if}
			</div>
		{/if}
	</div>
{/if}

<style>
	.wrap {
		position: relative;
		display: inline-flex;
	}
	.trigger {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 5px 9px;
		font-size: 12px;
		color: var(--text-muted);
		background: var(--bg-subtle);
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}
	.trigger:hover,
	.trigger.active {
		color: var(--text);
		border-color: var(--border-strong);
	}
	.panel {
		position: absolute;
		top: calc(100% + 6px);
		right: 0;
		z-index: 30;
		width: 320px;
		max-width: 90vw;
		padding: 12px;
		background: var(--bg);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-md);
		box-shadow: 0 12px 36px rgba(0, 0, 0, 0.45);
	}
	.panel-head {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 8px;
	}
	.panel-title {
		font-size: 12.5px;
		font-weight: 600;
	}
	.x {
		margin-left: auto;
		display: inline-flex;
		color: var(--text-dim);
		background: none;
		border: none;
		padding: 2px;
		cursor: pointer;
	}
	.x:hover {
		color: var(--text);
	}
	.in {
		width: 100%;
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 7px 9px;
		font-size: 12.5px;
	}
	.in:focus {
		border-color: var(--accent);
	}
	.foot {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-top: 8px;
	}
	.hint {
		flex: 1;
		font-size: 11px;
		color: var(--text-dim);
	}
	.err {
		margin: 8px 0 0;
		font-size: 11.5px;
		color: var(--danger);
	}
</style>
