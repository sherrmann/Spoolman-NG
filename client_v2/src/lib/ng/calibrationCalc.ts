/**
 * The calibration wizard's interactive calculators, as pure functions (#123).
 *
 * Extracted deliberately. In the React client this arithmetic lives inline in
 * CalibrationWizard.tsx AND again, copy-pasted, in StepResultDrawer.tsx -- the same formulas
 * written twice, which is exactly the kind of duplication that drifts. Here it is one module
 * with tests, and both the wizard and the standalone step editor call it.
 *
 * Every result is rounded to 5 decimal places, matching the React `parseFloat(x.toFixed(5))`.
 * That rounding is a contract, not cosmetics: a flow ratio is pasted into a slicer, and an
 * unrounded `1 + 0.02` would offer 1.0200000000000002.
 */

/** Round to the 5dp the flow calculators all use. */
function r5(value: number): number {
	return Number(value.toFixed(5));
}

const real = (v: number | null | undefined): v is number => typeof v === 'number' && !Number.isNaN(v);

/**
 * OrcaSlicer >= 2.3.0 "YOLO" single pass: the modifier is an ABSOLUTE adjustment to the ratio.
 *
 * Note the contrast with {@link legacyPass} below, which treats its modifier as a PERCENTAGE.
 * Mixing the two up yields a plausible-looking number rather than an error, so they are kept
 * as separate named functions rather than one with a flag.
 */
export function yoloFlowRatio(oldRatio: number | null, modifier: number | null): number | null {
	if (!real(oldRatio) || !real(modifier)) return null;
	return r5(oldRatio + modifier);
}

/** Legacy method, one pass: the modifier is a PERCENTAGE adjustment. */
export function legacyPass(ratio: number | null, modifier: number | null): number | null {
	if (!real(ratio) || !real(modifier)) return null;
	return r5((ratio * (100 + modifier)) / 100);
}

export type FlowCalcMethod = 'yolo' | 'legacy';

export interface FlowCalcState {
	method: FlowCalcMethod;
	yoloOld: number | null;
	yoloModifier: number | null;
	pass1Ratio: number | null;
	pass1Modifier: number | null;
	pass2Ratio: number | null;
	pass2Modifier: number | null;
}

/** A fresh calculator. The old ratio starts at 1.0, the slicer default. */
export function freshFlowCalc(method: FlowCalcMethod = 'yolo'): FlowCalcState {
	return {
		method,
		yoloOld: 1.0,
		yoloModifier: null,
		pass1Ratio: 1.0,
		pass1Modifier: null,
		pass2Ratio: null,
		pass2Modifier: null
	};
}

/**
 * The flow ratio this calculator would apply, or null while it is incomplete.
 *
 * The legacy method runs two passes and the second refines the first, so pass 2 wins when it
 * has been filled in and pass 1 stands alone until then.
 */
export function flowCalcResult(s: FlowCalcState): number | null {
	if (s.method === 'yolo') return yoloFlowRatio(s.yoloOld, s.yoloModifier);
	return legacyPass(s.pass2Ratio, s.pass2Modifier) ?? legacyPass(s.pass1Ratio, s.pass1Modifier);
}

/**
 * The avoidance-speed window a VFA artifact-speed list implies.
 *
 * An EMPTY list yields null rather than a window: `Math.min()` of nothing is Infinity, which
 * would silently store Infinity as a speed. The React client guards the same case by skipping
 * the update entirely, which also means clearing the list leaves the last computed window in
 * place rather than wiping a value the user may have typed by hand -- behaviour worth keeping,
 * and the reason this returns null instead of a zeroed window.
 */
export function avoidanceWindow(
	speeds: number[]
): { min_avoidance_speed: number; max_avoidance_speed: number } | null {
	const usable = speeds.filter(real);
	if (usable.length === 0) return null;
	return {
		min_avoidance_speed: Math.min(...usable),
		max_avoidance_speed: Math.max(...usable)
	};
}

/** Add a speed to the list, kept sorted ascending. Ignores a blank or NaN entry. */
export function addSpeed(speeds: number[], next: number | null): number[] {
	if (!real(next)) return speeds;
	return [...speeds, next].sort((a, b) => a - b);
}
