<script lang="ts">
	// A compact, dependency-free SVG line chart of a spool's measured gross weight over time
	// (#104, ported from client/src/pages/spools/weightHistoryChart.tsx). Nothing is charted
	// until a spool has been weighed twice, so the inspector is unchanged for most spools.
	//
	// The maths lives in $lib/ng/weightHistory so it can be tested; this file only draws it.
	import { isAbortError } from '$lib/api/http';
	import { live } from '$lib/api/live';
	import { ng } from '$lib/ng/i18n';
	import { listSpoolEvents } from '$lib/ng/usageEventsApi';
	import {
		CHART_SIZE,
		IDLE_GAIN_THRESHOLD_G,
		chartGeometry,
		maxIdleGain,
		measureSeries,
		type WeightPoint
	} from '$lib/ng/weightHistory';
	import { formatDateTime } from '$lib/utils/datetime';
	import { grams } from '$lib/utils/format';

	let { spoolId }: { spoolId: number } = $props();

	let series = $state<WeightPoint[]>([]);

	// Reruns whenever the inspector is pointed at a different spool; the effect owns one
	// AbortController, which cancels whatever is in flight when it is torn down.
	$effect(() => {
		const id = spoolId;
		// The inspector reuses this component across selections, so the previous spool's series
		// (and its moisture hint) must not stay on screen under the new spool's header while the
		// new fetch is in flight. A write, so it creates no dependency.
		series = [];
		const controller = new AbortController();

		const load = () =>
			listSpoolEvents(id, controller.signal)
				.then((events) => {
					series = measureSeries(events);
				})
				.catch((e) => {
					if (isAbortError(e, controller.signal)) return;
					console.error('Failed to load spool weight history', e);
					series = [];
				});

		load();
		// A weigh-in from the inspector's own adjust panel goes through the backend, which
		// broadcasts an `updated` event for this spool -- so refetch and redraw rather than
		// leaving a chart that is one measurement out of date until the next reload. The id is
		// passed as a number because live.ts compares it strictly against the payload's own.
		const unsubscribe = live.subscribe('spool', { id }, () => void load());

		return () => {
			unsubscribe();
			controller.abort();
		};
	});

	let gain = $derived(maxIdleGain(series));
	let geometry = $derived(chartGeometry(series, CHART_SIZE));

	function dotTitle(point: WeightPoint): string {
		return `${formatDateTime(point.time)}: ${grams(point.weight)} g`;
	}
</script>

{#if geometry}
	<section class="wh">
		<h3 class="title">{ng.spool_weight_history_title()}</h3>
		{#if gain >= IDLE_GAIN_THRESHOLD_G}
			<p class="hint">{ng.spool_weight_history_idle_gain({ grams: gain.toFixed(1) })}</p>
		{/if}
		<svg
			viewBox="0 0 {CHART_SIZE.w} {CHART_SIZE.h}"
			width="100%"
			role="img"
			aria-label={ng.spool_weight_history_chart_label()}
		>
			<text class="axis" x={geometry.labelX} y={geometry.maxY + 4} text-anchor="end">
				{Math.round(geometry.maxWeight)}
			</text>
			<text class="axis" x={geometry.labelX} y={geometry.minY + 4} text-anchor="end">
				{Math.round(geometry.minWeight)}
			</text>
			<line
				class="gridline"
				x1={geometry.gridX1}
				y1={geometry.maxY}
				x2={geometry.gridX2}
				y2={geometry.maxY}
			/>
			<line
				class="gridline"
				x1={geometry.gridX1}
				y1={geometry.minY}
				x2={geometry.gridX2}
				y2={geometry.minY}
			/>
			<polyline class="line" points={geometry.points} />
			{#each geometry.dots as dot (dot.point.time + dot.x)}
				<circle class="dot" cx={dot.x} cy={dot.y} r="3">
					<title>{dotTitle(dot.point)}</title>
				</circle>
			{/each}
		</svg>
	</section>
{/if}

<style>
	.wh {
		padding: 18px 20px;
		border-bottom: 1px solid var(--border-soft);
	}
	.title {
		margin: 0 0 10px;
		font-size: 11px;
		font-weight: 400;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: var(--text-dim);
	}
	.hint {
		margin: 0 0 10px;
		font-size: 12px;
		line-height: 1.4;
		color: var(--text-muted);
	}
	svg {
		display: block;
		/* The labels and gridlines are drawn in currentColor so the two share one definition. */
		color: var(--text-dim);
		overflow: visible;
	}
	.axis {
		fill: currentColor;
		font-size: 10px;
		opacity: 0.7;
	}
	.gridline {
		stroke: currentColor;
		opacity: 0.15;
	}
	.line {
		fill: none;
		stroke: var(--accent);
		stroke-width: 2;
		stroke-linejoin: round;
		stroke-linecap: round;
	}
	.dot {
		fill: var(--accent);
	}
</style>
