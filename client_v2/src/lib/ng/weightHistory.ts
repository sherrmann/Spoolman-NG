/**
 * Weight-history analysis for the spool inspector (#104), ported from
 * `client/src/pages/spools/weightHistory.ts`.
 *
 * Derived purely from the existing usage-event log -- measure events carry a gross
 * `measured_weight` -- so there is no new API and no new table. Pure functions, including the
 * SVG maths, so the series building, the moisture hint and the chart's coordinates are all
 * unit-tested rather than only being looked at.
 */
import type { SpoolUsageEvent } from './usageEventsApi';

export interface WeightPoint {
	time: string;
	weight: number;
}

/**
 * Chronological (oldest-first) series of measured gross weights, taken from measure events.
 * Events arrive newest-first from the API; this normalises them to time order for plotting.
 *
 * Ties are broken on the event id, which the backend assigns in insertion order. Timestamps are
 * recorded to the second, so two weigh-ins moments apart genuinely share one -- and sorting on
 * time alone leaves them in the newest-first order the API returned, because the sort is stable.
 * That draws the series backwards, which turns ordinary consumption into a rise and raises the
 * moisture hint on a spool that only ever got lighter. (The React original sorts on time alone
 * and has this defect.)
 */
export function measureSeries(events: SpoolUsageEvent[]): WeightPoint[] {
	return events
		.filter((e) => e.eventType === 'measure' && typeof e.measuredWeight === 'number')
		.sort((a, b) => a.time.localeCompare(b.time) || a.id - b.id)
		.map((e) => ({ time: e.time, weight: e.measuredWeight as number }));
}

/**
 * Largest increase in measured gross weight between two consecutive measurements, in grams.
 *
 * Filament is only ever consumed, so a measured spool getting *heavier* over time suggests it
 * has absorbed moisture (a refill would too -- hence this is surfaced only as an experimental
 * hint, never as a hard claim). Returns 0 when the trend is monotonically non-increasing, or
 * when there are fewer than two measurements.
 */
export function maxIdleGain(series: WeightPoint[]): number {
	let maxGain = 0;
	for (let i = 1; i < series.length; i++) {
		const gain = series[i].weight - series[i - 1].weight;
		if (gain > maxGain) {
			maxGain = gain;
		}
	}
	return maxGain;
}

/** Below this many grams, a measured increase is scale noise rather than a moisture hint. */
export const IDLE_GAIN_THRESHOLD_G = 2;

export interface ChartSize {
	/** viewBox width and height, in user units. */
	w: number;
	h: number;
	pad: { top: number; right: number; bottom: number; left: number };
}

/** The chart's own coordinate space. The SVG scales to its container, so these are not pixels. */
export const CHART_SIZE: ChartSize = {
	w: 600,
	h: 160,
	// Room on the left for the two weight labels; a hair elsewhere so the end dots are not
	// clipped by the viewBox.
	pad: { top: 12, right: 12, bottom: 12, left: 48 }
};

export interface ChartDot {
	x: number;
	y: number;
	point: WeightPoint;
}

export interface ChartGeometry {
	/** `x,y` pairs for the `<polyline>`, in drawing order. */
	points: string;
	dots: ChartDot[];
	minWeight: number;
	maxWeight: number;
	/** Where the lowest and highest weights sit vertically -- gridlines and labels share these. */
	minY: number;
	maxY: number;
	/** Right edge of the (right-aligned) weight labels. */
	labelX: number;
	/** Horizontal extent of the two gridlines. */
	gridX1: number;
	gridX2: number;
}

/**
 * Coordinates for the whole chart, or `null` when there is nothing worth drawing.
 *
 * A single measurement is a dot, not a history, so fewer than two points yields nothing at all
 * and the caller renders no chart. A *flat* series is a history and does draw: its span is
 * zero, which would divide every y coordinate into `NaN`, so the span falls back to 1 and the
 * line runs along the bottom of the plot.
 */
export function chartGeometry(series: WeightPoint[], size: ChartSize = CHART_SIZE): ChartGeometry | null {
	if (series.length < 2) return null;

	const weights = series.map((p) => p.weight);
	const minWeight = Math.min(...weights);
	const maxWeight = Math.max(...weights);
	const span = maxWeight - minWeight || 1;
	const innerW = size.w - size.pad.left - size.pad.right;
	const innerH = size.h - size.pad.top - size.pad.bottom;

	const x = (i: number) => size.pad.left + (i / (series.length - 1)) * innerW;
	const y = (weight: number) => size.pad.top + innerH - ((weight - minWeight) / span) * innerH;

	const dots = series.map((point, i) => ({ x: x(i), y: y(point.weight), point }));

	return {
		points: dots.map((d) => `${d.x},${d.y}`).join(' '),
		dots,
		minWeight,
		maxWeight,
		minY: y(minWeight),
		maxY: y(maxWeight),
		labelX: size.pad.left - 6,
		gridX1: size.pad.left,
		gridX2: size.w - size.pad.right
	};
}
