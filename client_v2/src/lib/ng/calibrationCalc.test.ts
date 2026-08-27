import { describe, it, expect } from 'vitest';
import {
	yoloFlowRatio,
	legacyPass,
	flowCalcResult,
	freshFlowCalc,
	avoidanceWindow,
	addSpeed
} from './calibrationCalc';

/**
 * The flow-rate and VFA calculators (#123).
 *
 * These matter more than their size suggests: the numbers come out of this module and go
 * straight into a slicer, so both the arithmetic AND its rounding are the contract. The React
 * client wrote each formula twice (wizard and drawer) with no test on either.
 */

describe('the YOLO flow method', () => {
	it('adds the modifier as an absolute adjustment', () => {
		expect(yoloFlowRatio(1.0, 0.02)).toBe(1.02);
		expect(yoloFlowRatio(0.98, -0.03)).toBe(0.95);
	});

	it('rounds away float error rather than passing it to the slicer', () => {
		// 1 + 0.02 is 1.0200000000000002 unrounded.
		expect(String(yoloFlowRatio(1, 0.02))).toBe('1.02');
		expect(String(yoloFlowRatio(0.1, 0.2))).toBe('0.3');
	});

	it('is null until both inputs are real numbers', () => {
		expect(yoloFlowRatio(null, 0.02)).toBeNull();
		expect(yoloFlowRatio(1.0, null)).toBeNull();
		expect(yoloFlowRatio(NaN, 0.02)).toBeNull();
	});
});

describe('the legacy flow method', () => {
	it('applies the modifier as a percentage, not an absolute', () => {
		// The distinction that makes these two separate functions: +5 here means +5%, so
		// 1.0 becomes 1.05 -- whereas YOLO's +5 would mean 6.0.
		expect(legacyPass(1.0, 5)).toBe(1.05);
		expect(legacyPass(1.0, -5)).toBe(0.95);
		expect(legacyPass(0.95, 5)).toBe(0.9975);
	});

	it('is null until both inputs are real numbers', () => {
		expect(legacyPass(1.0, null)).toBeNull();
		expect(legacyPass(null, 5)).toBeNull();
	});
});

describe('which value the calculator applies', () => {
	it('uses the YOLO result in yolo mode', () => {
		const s = { ...freshFlowCalc('yolo'), yoloOld: 1.0, yoloModifier: 0.02 };
		expect(flowCalcResult(s)).toBe(1.02);
	});

	it('uses pass 1 alone until pass 2 is filled in', () => {
		const s = { ...freshFlowCalc('legacy'), pass1Ratio: 1.0, pass1Modifier: 5 };
		expect(flowCalcResult(s)).toBe(1.05);
	});

	it('lets pass 2 refine pass 1 once it is complete', () => {
		const s = {
			...freshFlowCalc('legacy'),
			pass1Ratio: 1.0,
			pass1Modifier: 5,
			pass2Ratio: 1.05,
			pass2Modifier: -2
		};
		expect(flowCalcResult(s)).toBe(1.029);
	});

	it('falls back to pass 1 when pass 2 is only half filled', () => {
		const s = {
			...freshFlowCalc('legacy'),
			pass1Ratio: 1.0,
			pass1Modifier: 5,
			pass2Ratio: 1.05,
			pass2Modifier: null
		};
		expect(flowCalcResult(s)).toBe(1.05);
	});

	it('is null while nothing has been entered', () => {
		expect(flowCalcResult(freshFlowCalc('yolo'))).toBeNull();
		expect(flowCalcResult(freshFlowCalc('legacy'))).toBeNull();
	});

	it('starts from the slicer default ratio of 1.0', () => {
		expect(freshFlowCalc().yoloOld).toBe(1);
		expect(freshFlowCalc('legacy').pass1Ratio).toBe(1);
	});
});

describe('the VFA avoidance window', () => {
	it('spans the slowest and fastest artifact speeds', () => {
		expect(avoidanceWindow([120, 80, 200])).toEqual({
			min_avoidance_speed: 80,
			max_avoidance_speed: 200
		});
	});

	it('handles a single speed as a degenerate window', () => {
		expect(avoidanceWindow([150])).toEqual({
			min_avoidance_speed: 150,
			max_avoidance_speed: 150
		});
	});

	it('returns null for an empty list rather than an Infinity window', () => {
		// Math.min() of nothing is Infinity; storing that as a speed would be worse than
		// storing nothing. Null lets the caller leave whatever is there alone.
		expect(avoidanceWindow([])).toBeNull();
		expect(avoidanceWindow([NaN])).toBeNull();
	});
});

describe('adding an artifact speed', () => {
	it('keeps the list sorted ascending', () => {
		let list: number[] = [];
		list = addSpeed(list, 200);
		list = addSpeed(list, 80);
		list = addSpeed(list, 120);
		expect(list).toEqual([80, 120, 200]);
	});

	it('ignores a blank or NaN entry rather than poisoning the list', () => {
		expect(addSpeed([80], null)).toEqual([80]);
		expect(addSpeed([80], NaN)).toEqual([80]);
	});

	it('keeps duplicates, since two artifacts can appear at one speed', () => {
		expect(addSpeed([80], 80)).toEqual([80, 80]);
	});
});
