import { describe, expect, it } from 'vitest';
import { CHART_SIZE, chartGeometry, maxIdleGain, measureSeries } from './weightHistory';
import type { SpoolUsageEvent } from './usageEventsApi';

function event(over: Partial<SpoolUsageEvent> = {}): SpoolUsageEvent {
	return { id: 1, spoolId: 1, time: '2026-07-01T00:00:00Z', eventType: 'use', delta: 10, ...over };
}

describe('measureSeries', () => {
	it('keeps only measure events with a measured weight, oldest-first', () => {
		const events: SpoolUsageEvent[] = [
			event({ time: '2026-07-03T00:00:00Z', eventType: 'measure', measuredWeight: 800 }),
			event({ time: '2026-07-02T00:00:00Z', eventType: 'use', delta: 50 }),
			event({ time: '2026-07-01T00:00:00Z', eventType: 'measure', measuredWeight: 900 })
		];
		expect(measureSeries(events)).toEqual([
			{ time: '2026-07-01T00:00:00Z', weight: 900 },
			{ time: '2026-07-03T00:00:00Z', weight: 800 }
		]);
	});

	// Timestamps are recorded to the second, so two weigh-ins moments apart share one. Sorting
	// on time alone is stable, which would leave the pair in the newest-first order the API
	// returned -- reversing the series and reading a falling weight as a rise.
	it('breaks a tied timestamp on the event id, oldest first', () => {
		const events: SpoolUsageEvent[] = [
			event({ id: 2, time: '2026-07-01T09:00:00Z', eventType: 'measure', measuredWeight: 800 }),
			event({ id: 1, time: '2026-07-01T09:00:00Z', eventType: 'measure', measuredWeight: 900 })
		];
		expect(measureSeries(events).map((p) => p.weight)).toEqual([900, 800]);
	});

	it('ignores measure events without a measured weight', () => {
		expect(measureSeries([event({ eventType: 'measure' })])).toEqual([]);
	});

	it('returns an empty series when there are no measurements', () => {
		expect(measureSeries([event(), event({ eventType: 'update' })])).toEqual([]);
	});
});

describe('maxIdleGain', () => {
	it('is 0 for a monotonically decreasing (normal consumption) series', () => {
		expect(
			maxIdleGain([
				{ time: 'a', weight: 900 },
				{ time: 'b', weight: 800 },
				{ time: 'c', weight: 750 }
			])
		).toBe(0);
	});

	it('reports the largest upward jump between consecutive measurements', () => {
		// 900 -> 830 (down) -> 845 (+15) -> 840 (down): the max gain is 15.
		expect(
			maxIdleGain([
				{ time: 'a', weight: 900 },
				{ time: 'b', weight: 830 },
				{ time: 'c', weight: 845 },
				{ time: 'd', weight: 840 }
			])
		).toBe(15);
	});

	it('is 0 for a series with fewer than two points', () => {
		expect(maxIdleGain([{ time: 'a', weight: 900 }])).toBe(0);
		expect(maxIdleGain([])).toBe(0);
	});
});

describe('chartGeometry', () => {
	const { w, h, pad } = CHART_SIZE;
	const top = pad.top;
	const bottom = h - pad.bottom;

	it('draws nothing for fewer than two points', () => {
		expect(chartGeometry([])).toBeNull();
		expect(chartGeometry([{ time: 'a', weight: 900 }])).toBeNull();
	});

	it('puts the heaviest measurement at the top and the lightest at the bottom', () => {
		const geo = chartGeometry([
			{ time: 'a', weight: 900 },
			{ time: 'b', weight: 800 },
			{ time: 'c', weight: 850 }
		]);
		expect(geo).not.toBeNull();
		expect(geo?.maxWeight).toBe(900);
		expect(geo?.minWeight).toBe(800);
		expect(geo?.maxY).toBe(top);
		expect(geo?.minY).toBe(bottom);
		// Middle value, middle of the plot.
		expect(geo?.dots[2].y).toBeCloseTo((top + bottom) / 2, 6);
	});

	it('spans the plot horizontally, first point to last', () => {
		const geo = chartGeometry([
			{ time: 'a', weight: 900 },
			{ time: 'b', weight: 850 },
			{ time: 'c', weight: 800 }
		]);
		expect(geo?.dots[0].x).toBe(pad.left);
		expect(geo?.dots[2].x).toBe(w - pad.right);
		expect(geo?.points).toBe(geo?.dots.map((d) => `${d.x},${d.y}`).join(' '));
		expect(geo?.gridX1).toBe(pad.left);
		expect(geo?.gridX2).toBe(w - pad.right);
	});

	// A spool weighed twice at the same value has a zero span. Dividing by it would put every
	// coordinate at NaN, and an SVG polyline with a NaN in its points list draws nothing at all.
	it('keeps a flat series on the chart rather than dividing by a zero span', () => {
		const geo = chartGeometry([
			{ time: 'a', weight: 850 },
			{ time: 'b', weight: 850 }
		]);
		expect(geo?.dots.every((d) => Number.isFinite(d.x) && Number.isFinite(d.y))).toBe(true);
		expect(geo?.dots.map((d) => d.y)).toEqual([bottom, bottom]);
		expect(geo?.minWeight).toBe(850);
		expect(geo?.maxWeight).toBe(850);
	});
});
