import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
	ADJUST_MODE_KEY,
	currentId,
	failed,
	finish,
	isFinished,
	parseAdjustMode,
	parseReading,
	saved,
	skip,
	startWeighIn,
	weighSummary
} from './weighIn';

describe('the weigh-in stepper', () => {
	it('walks the queue in order', () => {
		let s = startWeighIn([7, 3, 9]);
		expect(currentId(s)).toBe(7);
		s = saved(s);
		expect(currentId(s)).toBe(3);
		s = saved(saved(s));
		expect(isFinished(s)).toBe(true);
		expect(s.results.map((r) => r.id)).toEqual([7, 3, 9]);
	});

	it('skips without saving', () => {
		const s = saved(skip(startWeighIn([1, 2])));
		expect(s.results).toEqual([
			{ id: 1, status: 'skipped' },
			{ id: 2, status: 'updated' }
		]);
	});

	it('stays on a spool whose save failed, so it can be retried', () => {
		let s = failed(startWeighIn([1, 2]), 'offline');
		expect(currentId(s)).toBe(1);
		expect(s.pendingError).toBe('offline');
		s = saved(s);
		expect(s.results).toEqual([{ id: 1, status: 'updated' }]);
		expect(s.pendingError).toBeNull();
	});

	it('records a spool skipped after a failed save as failed, with the reason', () => {
		const s = skip(failed(startWeighIn([1, 2]), 'offline'));
		expect(s.results).toEqual([{ id: 1, status: 'failed', error: 'offline' }]);
		expect(currentId(s)).toBe(2);
	});

	it('stops early, leaving unreached spools out of the results', () => {
		const s = finish(saved(startWeighIn([1, 2, 3])));
		expect(isFinished(s)).toBe(true);
		expect(s.results).toEqual([{ id: 1, status: 'updated' }]);
	});

	it('stopping on a failed spool still reports the failure', () => {
		const s = finish(failed(startWeighIn([1, 2]), 'offline'));
		expect(s.results).toEqual([{ id: 1, status: 'failed', error: 'offline' }]);
	});

	it('does nothing once finished', () => {
		const done = finish(startWeighIn([1]));
		expect(saved(done)).toBe(done);
		expect(skip(done)).toBe(done);
		expect(failed(done, 'x')).toBe(done);
	});

	it('counts the outcomes', () => {
		expect(
			weighSummary([
				{ id: 1, status: 'updated' },
				{ id: 2, status: 'updated' },
				{ id: 3, status: 'skipped' },
				{ id: 4, status: 'failed', error: 'x' }
			])
		).toEqual({ updated: 2, skipped: 1, failed: 1 });
	});
});

describe('parseReading', () => {
	// The inspector's rules: a number is required; only a measured gross weight must not be negative.
	it.each([
		['12.5', 'length', { value: 12.5 }],
		['-4', 'length', { value: -4 }],
		['-4', 'weight', { value: -4 }],
		['1234,5', 'measured_weight', { value: 1234.5 }],
		['0', 'measured_weight', { value: 0 }],
		['-1', 'measured_weight', { error: 'weight' }],
		['', 'length', { error: 'length' }],
		['', 'weight', { error: 'weight' }],
		// Stricter than the inspector's parseFloat, which would read these as 12 and 100.
		['12abc', 'weight', { error: 'weight' }],
		['1e2', 'measured_weight', { error: 'weight' }]
	] as const)('%s as %s', (raw, mode, expected) => {
		expect(parseReading(raw, mode)).toEqual(expected);
	});
});

describe('the adjust mode shared with the inspector', () => {
	it('reads a stored mode the way the inspector does', () => {
		expect(parseAdjustMode('weight')).toBe('weight');
		expect(parseAdjustMode('measured_weight')).toBe('measured_weight');
		expect(parseAdjustMode(null)).toBe('length');
		expect(parseAdjustMode('grams')).toBe('length');
	});

	it('uses the key the inspector still uses', () => {
		// The key is a local constant in upstream's SpoolInspector, copied here. A subtree pull
		// that renames it would leave the two panels keeping separate modes with nothing looking
		// broken, so this fails instead.
		const inspector = readFileSync(
			new URL('../components/library/SpoolInspector.svelte', import.meta.url),
			'utf8'
		);
		expect(inspector).toContain(`const ADJUST_MODE_KEY = '${ADJUST_MODE_KEY}';`);
	});
});
