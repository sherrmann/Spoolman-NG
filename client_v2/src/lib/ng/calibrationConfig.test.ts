import { describe, it, expect } from 'vitest';
import {
	STEP_CONFIGS,
	AUTO_COMPUTE,
	WIZARD_STEP_ORDER,
	fieldSection,
	type StepField
} from './calibrationConfig';
import { isSkipped, type CalibrationStepResult } from './calibrationTypes';

/**
 * The calibration step table and its formulas (#123).
 *
 * The table was generated from the React source rather than retyped, so these tests are not
 * trying to catch a transcription slip in the 36 field definitions. They pin the things a
 * later edit could plausibly break: the arithmetic, its ROUNDING (these numbers get pasted
 * into a slicer, so 0.30000000000000004 is a real defect, not a cosmetic one), the
 * half-filled-form behaviour, and the invariants the port relies on.
 */

const allFields = (): { step: string; field: StepField; section: string }[] =>
	Object.entries(STEP_CONFIGS).flatMap(([step, cfg]) =>
		[...cfg.inputFields, ...cfg.outputFields].map((field) => ({
			step,
			field,
			section: fieldSection(cfg, field)
		}))
	);

describe('the step table', () => {
	it('covers every step in the wizard order, and nothing else', () => {
		expect(Object.keys(STEP_CONFIGS).sort()).toEqual([...WIZARD_STEP_ORDER].sort());
	});

	it('lists the steps in the backend enum order', () => {
		// Both clients and the API agree on this order (calibration_models.py:16-25). A
		// reordering here would silently renumber "Step 3 of 9" against the other client.
		expect(WIZARD_STEP_ORDER).toEqual([
			'temperature',
			'volumetric_speed',
			'pressure_advance',
			'flow_rate',
			'retraction',
			'tolerance',
			'cornering',
			'input_shaping',
			'vfa'
		]);
	});

	it('derives each field section from the array it lives in', () => {
		for (const { step, field, section } of allFields()) {
			const expected = STEP_CONFIGS[step as keyof typeof STEP_CONFIGS].inputFields.includes(field)
				? 'inputs'
				: 'outputs';
			expect(section, `${step}.${field.key}`).toBe(expected);
		}
	});

	it('recommends only keys that step declares as outputs', () => {
		for (const [step, cfg] of Object.entries(STEP_CONFIGS)) {
			const outputs = cfg.outputFields.map((f) => f.key);
			for (const key of cfg.recommendedKeys) {
				expect(outputs, `${step} recommends ${key}`).toContain(key);
			}
		}
	});

	it('gives every select field a non-empty option list', () => {
		for (const { step, field } of allFields()) {
			if (field.type !== 'select') continue;
			expect(field.options, `${step}.${field.key}`).toBeDefined();
			expect(field.options!.length, `${step}.${field.key}`).toBeGreaterThan(0);
		}
	});

	it('uses unique field keys within each section', () => {
		// Uniqueness is per SECTION, not per step: `inputs` and `outputs` are separate JSON
		// blobs on the wire, so the same key in both is not a collision. input_shaping really
		// does this -- frequency_x/frequency_y are both the frequency you TESTED at and the
		// one you settled on. A duplicate inside one array would silently overwrite on save.
		for (const [step, cfg] of Object.entries(STEP_CONFIGS)) {
			for (const [section, fields] of [
				['inputs', cfg.inputFields],
				['outputs', cfg.outputFields]
			] as const) {
				const keys = fields.map((f) => f.key);
				expect(new Set(keys).size, `${step}.${section}`).toBe(keys.length);
			}
		}
	});

	it('keeps a key that appears in both sections meaning the same measurement', () => {
		// Guards the reading above: if a future edit reuses a key across sections for two
		// DIFFERENT quantities, the recommended-settings summary would show one labelled as
		// the other. Today only input_shaping reuses keys, and deliberately.
		const reused = Object.entries(STEP_CONFIGS).flatMap(([step, cfg]) => {
			const inputs = new Set(cfg.inputFields.map((f) => f.key));
			return cfg.outputFields.filter((f) => inputs.has(f.key)).map((f) => `${step}.${f.key}`);
		});
		expect(reused).toEqual(['input_shaping.frequency_x', 'input_shaping.frequency_y']);
	});
});

describe('auto-computed values', () => {
	it('computes volumetric speed as start + height x step, to 2dp', () => {
		expect(AUTO_COMPUTE.volumetric_speed!({ start_speed: 5, step_size: 0.5, measured_height: 12 })).toEqual({
			max_volumetric_speed: 11
		});
	});

	it('computes pressure advance as A x B, to 4dp', () => {
		expect(AUTO_COMPUTE.pressure_advance!({ pa_step_a: 0.002, measured_height_b: 17 })).toEqual({
			pressure_advance: 0.034
		});
	});

	it('computes retraction as start + height x factor, to 5dp', () => {
		expect(AUTO_COMPUTE.retraction!({ start_retract: 0, measured_height: 7.5, factor: 0.1 })).toEqual({
			retraction_length: 0.75
		});
	});

	it('computes tolerance as test - measured, to 3dp', () => {
		expect(AUTO_COMPUTE.tolerance!({ test_size: 20, measured_size: 19.87 })).toEqual({
			tolerance_offset: 0.13
		});
	});

	it('rounds rather than letting float error through', () => {
		// 0.1 + 0.2 is the canonical case: unrounded this yields 0.30000000000000004, which
		// would be pasted into a slicer field verbatim.
		expect(AUTO_COMPUTE.retraction!({ start_retract: 0.1, measured_height: 1, factor: 0.2 })).toEqual({
			retraction_length: 0.3
		});
		expect(AUTO_COMPUTE.tolerance!({ test_size: 0.3, measured_size: 0.1 })).toEqual({
			tolerance_offset: 0.2
		});
	});

	it('leaves the output alone until every input it needs is present', () => {
		expect(AUTO_COMPUTE.volumetric_speed!({ start_speed: 5, step_size: null, measured_height: 12 })).toEqual(
			{}
		);
		expect(AUTO_COMPUTE.pressure_advance!({ pa_step_a: 0.002 })).toEqual({});
		expect(AUTO_COMPUTE.tolerance!({ test_size: NaN, measured_size: 1 })).toEqual({});
	});

	it('only defines a formula for steps that had one', () => {
		expect(Object.keys(AUTO_COMPUTE).sort()).toEqual([
			'pressure_advance',
			'retraction',
			'tolerance',
			'volumetric_speed'
		]);
	});

	it('writes into a key that step actually declares as an output', () => {
		for (const [step, fn] of Object.entries(AUTO_COMPUTE)) {
			const outputs = STEP_CONFIGS[step as keyof typeof STEP_CONFIGS].outputFields.map((f) => f.key);
			// Feed it 1 for everything so the formula runs whatever inputs it wants.
			const inputs = Object.fromEntries(
				STEP_CONFIGS[step as keyof typeof STEP_CONFIGS].inputFields.map((f) => [f.key, 1])
			);
			for (const key of Object.keys(fn!(inputs))) {
				expect(outputs, `${step} computes ${key}`).toContain(key);
			}
		}
	});
});

describe('the skip sentinel', () => {
	const step = (outputs?: Record<string, unknown>): CalibrationStepResult => ({
		id: 1,
		sessionId: 1,
		stepType: 'temperature',
		outputs,
		recordedAt: '2026-01-01T00:00:00Z'
	});

	it('reads a step the React client skipped', () => {
		// Both clients share one database, so this spelling is a compatibility contract.
		expect(isSkipped(step({ _skipped: true }))).toBe(true);
	});

	it('does not treat an unrecorded or ordinary step as skipped', () => {
		expect(isSkipped(step(undefined))).toBe(false);
		expect(isSkipped(step({}))).toBe(false);
		expect(isSkipped(step({ temperature: 210 }))).toBe(false);
		expect(isSkipped(step({ _skipped: false }))).toBe(false);
	});
});
