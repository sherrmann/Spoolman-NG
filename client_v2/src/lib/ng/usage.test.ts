import { describe, expect, it } from 'vitest';
import { axisLabel } from './usage';

describe('axisLabel', () => {
	it('passes a year bucket through unchanged', () => {
		expect(axisLabel('2026', 'year', 'en-GB')).toBe('2026');
	});

	it('renders a month bucket in the given locale', () => {
		expect(axisLabel('2026-07', 'month', 'en-GB')).toBe('Jul 26');
		expect(axisLabel('2026-07', 'month', 'de-DE')).toMatch(/26/);
	});

	it('keeps the month/day tail for day and week buckets', () => {
		expect(axisLabel('2026-07-04', 'day', 'en-GB')).toBe('07-04');
		expect(axisLabel('2026-12-29', 'week', 'en-GB')).toBe('12-29');
	});

	it('handles the December boundary without rolling into the next year', () => {
		expect(axisLabel('2026-12', 'month', 'en-GB')).toBe('Dec 26');
		expect(axisLabel('2026-01', 'month', 'en-GB')).toBe('Jan 26');
	});

	// A month index is 1-based on the wire and 0-based in Date, so an unguarded conversion turns
	// "2026-13" into January of the following year -- a plausible-looking wrong label.
	it('renders a malformed period as-is rather than inventing a date', () => {
		expect(axisLabel('2026-13', 'month', 'en-GB')).toBe('2026-13');
		expect(axisLabel('2026-00', 'month', 'en-GB')).toBe('2026-00');
		expect(axisLabel('not-a-date', 'month', 'en-GB')).toBe('not-a-date');
	});
});
