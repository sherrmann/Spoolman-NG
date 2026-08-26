<script lang="ts">
	import { isAbortError } from '$lib/api/http';
	import { usageStats } from '$lib/ng/api';
	import { ng } from '$lib/ng/i18n';
	import type { UsageBucket, UsageStat } from '$lib/ng/types';
	import { axisLabel } from '$lib/ng/usage';
	import { dateLocale } from '$lib/utils/datetime';
	import { weightAuto } from '$lib/utils/format';
	import { settings } from '$lib/stores/settings.svelte';

	// Home "Usage" tab: a dependency-free bar chart of filament consumed per time bucket,
	// driven by the additive /stats/usage endpoint (ported from client/src/pages/home/
	// usageChart.tsx). Bars are plain divs, matching the rest of Home's charts, so no
	// charting library is pulled in.

	const BUCKETS: UsageBucket[] = ['day', 'week', 'month', 'year'];
	// Keep the chart readable: only the most recent N buckets are plotted.
	const MAX_BARS = 12;

	let bucket = $state<UsageBucket>('month');
	let stats = $state<UsageStat[]>([]);
	let loading = $state(true);

	function bucketLabel(b: UsageBucket): string {
		switch (b) {
			case 'day':
				return ng.home_usage_bucket_day();
			case 'week':
				return ng.home_usage_bucket_week();
			case 'month':
				return ng.home_usage_bucket_month();
			case 'year':
				return ng.home_usage_bucket_year();
		}
	}

	let recent = $derived(stats.slice(-MAX_BARS));
	let maxWeight = $derived(Math.max(1, ...recent.map((s) => s.consumedWeight)));
	let totalWeight = $derived(recent.reduce((sum, s) => sum + s.consumedWeight, 0));
	let totalCost = $derived(recent.reduce((sum, s) => sum + s.cost, 0));

	function barTitle(s: UsageStat): string {
		const lines = [s.period, weightAuto(s.consumedWeight)];
		if (s.cost > 0) lines.push(settings.formatPrice(s.cost));
		return lines.join('\n');
	}

	// Reruns whenever `bucket` changes; the effect owns exactly one request at a time.
	$effect(() => {
		const b = bucket;
		const controller = new AbortController();
		loading = true;
		usageStats(b, controller.signal)
			.then((rows) => {
				stats = rows;
			})
			.catch((e) => {
				if (isAbortError(e, controller.signal)) return;
				console.error('Failed to load usage stats', e);
				stats = [];
			})
			.finally(() => {
				loading = false;
			});
		return () => controller.abort();
	});
</script>

<div class="wrap">
	<div class="toolbar">
		<div class="seg">
			{#each BUCKETS as b (b)}
				<button type="button" class="seg-btn" class:active={bucket === b} onclick={() => (bucket = b)}>
					{bucketLabel(b)}
				</button>
			{/each}
		</div>
		{#if recent.length > 0}
			<span class="summary">
				{weightAuto(totalWeight)}{totalCost > 0 ? ` · ${settings.formatPrice(totalCost)}` : ''}
			</span>
		{/if}
	</div>

	{#if loading}
		<p class="empty">{ng.home_usage_loading()}</p>
	{:else if recent.length === 0}
		<p class="empty">{ng.home_usage_empty()}</p>
	{:else}
		<div class="chart">
			{#each recent as s (s.period)}
				<div class="col" title={barTitle(s)}>
					<div class="track">
						<div class="bar" style="height:{Math.max((s.consumedWeight / maxWeight) * 100, 2)}%"></div>
					</div>
					<div class="xlabel">{axisLabel(s.period, bucket, dateLocale())}</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: 8px;
		margin-bottom: 16px;
	}
	.seg {
		display: inline-flex;
		border: 1px solid var(--border-strong);
		border-radius: 7px;
		overflow: hidden;
	}
	.seg-btn {
		padding: 6px 12px;
		background: none;
		border: none;
		border-right: 1px solid var(--border-strong);
		color: var(--text-2);
		font-size: 12px;
		cursor: pointer;
		font-family: inherit;
	}
	.seg-btn:last-child {
		border-right: none;
	}
	.seg-btn.active {
		background: var(--accent-wash);
		color: var(--accent-soft);
		font-weight: 600;
	}
	.summary {
		font-size: 13px;
		color: var(--text-dim);
	}
	.empty {
		text-align: center;
		padding: 32px;
		color: var(--text-faint);
		font-size: 13px;
	}
	.chart {
		display: flex;
		align-items: flex-end;
		gap: 6px;
		height: 180px;
		padding-top: 8px;
	}
	.col {
		flex: 1 1 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		min-width: 0;
		height: 100%;
	}
	.track {
		flex: 1 1 auto;
		width: 100%;
		max-width: 40px;
		display: flex;
		align-items: flex-end;
		border-radius: 4px;
		overflow: hidden;
		background: var(--track);
	}
	.bar {
		width: 100%;
		border-radius: 4px 4px 0 0;
		background: var(--accent);
		transition: height 0.2s ease;
	}
	.xlabel {
		margin-top: 6px;
		font-size: 11px;
		color: var(--text-dim);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
	}
</style>
