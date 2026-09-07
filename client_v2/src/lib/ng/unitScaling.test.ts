import { afterEach, describe, expect, it } from 'vitest';
import { effectiveUnitScaling, isUnitScaling, setUnitScaling } from './unitScaling.svelte';
import { weightAuto } from '$lib/utils/format';

const setting = (value: string, is_set = true) => ({ value, is_set, type: 'boolean' });

afterEach(() => setUnitScaling(true));

describe('effectiveUnitScaling', () => {
	it('keeps scaling on when the server has never been told otherwise', () => {
		// Upstream's behaviour, and what its own browser suite expects on a fresh database.
		expect(effectiveUnitScaling(undefined)).toBe(true);
		expect(effectiveUnitScaling(setting('false', false))).toBe(true);
	});

	it('follows an explicit choice', () => {
		expect(effectiveUnitScaling(setting('true'))).toBe(true);
		expect(effectiveUnitScaling(setting('false'))).toBe(false);
	});

	it('treats an unreadable value as the default rather than as "off"', () => {
		expect(effectiveUnitScaling(setting('not json'))).toBe(true);
	});
});

describe('weightAuto under the flag', () => {
	it('scales at 1000 g by default', () => {
		expect(isUnitScaling()).toBe(true);
		expect(weightAuto(1500)).toBe('1.5 kg');
		expect(weightAuto(864)).toBe('864 g');
	});

	it('shows raw grams once scaling is switched off, and nothing else changes', () => {
		setUnitScaling(false);
		expect(weightAuto(1500)).toBe('1500 g');
		expect(weightAuto(1000)).toBe('1000 g');
		expect(weightAuto(864)).toBe('864 g');
		// The one-decimal rounding still applies; only the unit switch is off.
		expect(weightAuto(1234.56)).toBe('1234.6 g');
	});

	it('comes back when switched on again', () => {
		setUnitScaling(false);
		setUnitScaling(true);
		expect(weightAuto(2000)).toBe('2 kg');
	});
});
