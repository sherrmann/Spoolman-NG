/**
 * Per-step field definitions and auto-compute formulas for calibration (#123).
 *
 * Ported from client/src/pages/calibration/stepConfig.ts, but MECHANICALLY: the React object
 * was transpiled and dumped, and this table generated from that dump, so no numeric constant
 * was retyped. 36 fields across 9 steps, and a typo in a min/max would have been invisible.
 *
 * Two things the React version carried are deliberately gone:
 *
 * - `label`. It held an English string that nothing rendered -- the UI resolves
 *   `calibration.field_labels.{section}.{key}` instead (CalibrationWizard.tsx:66), so the
 *   labels here were dead weight that could silently disagree with the catalogue.
 * - `section`. It restated which array the field already sits in; verified across all 36
 *   fields that the two never disagreed, so it is derived rather than stored. `fieldSection`
 *   below is the one place that mapping lives.
 *
 * Select options keep only their VALUES for the same reason: the option label comes from
 * `calibration.field_labels.options.{value}` (CalibrationWizard.tsx:51).
 *
 * Formula approach inspired by the Orca-Slicer-Assistant project
 * (https://github.com/ItsDeidara/Orca-Slicer-Assistant); step order is the OrcaSlicer wiki's.
 */
import type { CalibrationStepType } from './calibrationTypes';

/** Which half of the form a field belongs to; also the i18n key segment for its label. */
export type FieldSection = 'inputs' | 'outputs';

export interface StepField {
	key: string;
	type: 'number' | 'select';
	unit?: string;
	min?: number;
	max?: number;
	step?: number;
	precision?: number;
	/** Grid columns out of 24, matching the React layout's spans where it set one. */
	colSpan?: number;
	/** Permitted values for a `select`; each renders via calibration_field_labels_options_*. */
	options?: string[];
}

export interface StepConfig {
	inputFields: StepField[];
	outputFields: StepField[];
	/** Output keys whose values become the step's `selected_values` (the recommended settings). */
	recommendedKeys: string[];
}

export const STEP_CONFIGS: Record<CalibrationStepType, StepConfig> = {
	temperature: {
		inputFields: [
			{ key: 'start_temp', type: 'number', unit: '°C', min: 100, max: 400, precision: 0 },
			{ key: 'end_temp', type: 'number', unit: '°C', min: 100, max: 400, precision: 0 },
			{ key: 'step_size', type: 'number', unit: '°C', min: 1, max: 20, precision: 0 }
		],
		outputFields: [{ key: 'temperature', type: 'number', unit: '°C', min: 100, max: 400, precision: 0 }],
		recommendedKeys: ['temperature']
	},
	volumetric_speed: {
		inputFields: [
			{ key: 'start_speed', type: 'number', unit: 'mm³/s', min: 0, precision: 1 },
			{ key: 'step_size', type: 'number', unit: 'mm³/s', min: 0, precision: 1 },
			{ key: 'measured_height', type: 'number', unit: 'mm', min: 0, precision: 1 }
		],
		outputFields: [{ key: 'max_volumetric_speed', type: 'number', unit: 'mm³/s', min: 0, precision: 2 }],
		recommendedKeys: ['max_volumetric_speed']
	},
	pressure_advance: {
		inputFields: [
			{ key: 'extruder_type', type: 'select', options: ['direct_drive', 'bowden'] },
			{ key: 'pa_step_a', type: 'number', min: 0, step: 0.001, precision: 4 },
			{ key: 'measured_height_b', type: 'number', unit: 'mm', min: 0, precision: 1 }
		],
		outputFields: [{ key: 'pressure_advance', type: 'number', min: 0, max: 2, step: 0.001, precision: 4 }],
		recommendedKeys: ['pressure_advance']
	},
	flow_rate: {
		inputFields: [],
		outputFields: [{ key: 'flow_ratio', type: 'number', min: 0.5, max: 1.5, step: 1e-5, precision: 5 }],
		recommendedKeys: ['flow_ratio']
	},
	retraction: {
		inputFields: [
			{ key: 'start_retract', type: 'number', unit: 'mm', min: 0, max: 10, step: 0.1, precision: 2 },
			{ key: 'measured_height', type: 'number', unit: 'mm', min: 0, precision: 1 },
			{ key: 'factor', type: 'number', min: 0, step: 0.01, precision: 3 }
		],
		outputFields: [
			{ key: 'retraction_length', type: 'number', unit: 'mm', min: 0, max: 10, step: 1e-5, precision: 5 }
		],
		recommendedKeys: ['retraction_length']
	},
	tolerance: {
		inputFields: [
			{ key: 'test_size', type: 'number', unit: 'mm', min: 0, precision: 2 },
			{ key: 'measured_size', type: 'number', unit: 'mm', min: 0, precision: 3 }
		],
		outputFields: [{ key: 'tolerance_offset', type: 'number', unit: 'mm', step: 0.01, precision: 3 }],
		recommendedKeys: ['tolerance_offset']
	},
	cornering: {
		inputFields: [
			{
				key: 'firmware_type',
				type: 'select',
				options: ['junction_deviation', 'jerk', 'square_corner_velocity']
			},
			{ key: 'start_value', type: 'number', min: 0, step: 0.01, precision: 3 },
			{ key: 'end_value', type: 'number', min: 0, step: 0.01, precision: 3 }
		],
		outputFields: [{ key: 'cornering_value', type: 'number', min: 0, step: 0.01, precision: 3 }],
		recommendedKeys: ['cornering_value']
	},
	input_shaping: {
		inputFields: [
			{ key: 'shaper_type', type: 'select', options: ['mzv', 'ei', 'zv', '2hump_ei', '3hump_ei'] },
			{ key: 'frequency_x', type: 'number', unit: 'Hz', min: 0, precision: 1 },
			{ key: 'frequency_y', type: 'number', unit: 'Hz', min: 0, precision: 1 }
		],
		outputFields: [
			{
				key: 'shaper_type_x',
				type: 'select',
				colSpan: 12,
				options: ['mzv', 'ei', 'zv', '2hump_ei', '3hump_ei']
			},
			{ key: 'frequency_x', type: 'number', unit: 'Hz', min: 0, precision: 1, colSpan: 12 },
			{
				key: 'shaper_type_y',
				type: 'select',
				colSpan: 12,
				options: ['mzv', 'ei', 'zv', '2hump_ei', '3hump_ei']
			},
			{ key: 'frequency_y', type: 'number', unit: 'Hz', min: 0, precision: 1, colSpan: 12 }
		],
		recommendedKeys: ['shaper_type_x', 'frequency_x', 'shaper_type_y', 'frequency_y']
	},
	vfa: {
		inputFields: [
			{ key: 'start_speed', type: 'number', unit: 'mm/s', min: 0, precision: 0, colSpan: 8 },
			{ key: 'end_speed', type: 'number', unit: 'mm/s', min: 0, precision: 0, colSpan: 8 },
			{ key: 'step_size', type: 'number', unit: 'mm/s', min: 0, precision: 0, colSpan: 8 }
		],
		outputFields: [
			{ key: 'min_avoidance_speed', type: 'number', unit: 'mm/s', min: 0, precision: 0, colSpan: 12 },
			{ key: 'max_avoidance_speed', type: 'number', unit: 'mm/s', min: 0, precision: 0, colSpan: 12 }
		],
		recommendedKeys: ['min_avoidance_speed', 'max_avoidance_speed']
	}
};

/** The section a field belongs to, from the array it was read out of. */
export function fieldSection(config: StepConfig, field: StepField): FieldSection {
	return config.inputFields.includes(field) ? 'inputs' : 'outputs';
}

/**
 * Values a step can compute for the user from what they measured.
 *
 * All four are one line of arithmetic, and the rounding is part of the contract, not
 * cosmetic: these numbers are pasted into a slicer, and `0.1 + 0.2` style drift would put
 * `0.30000000000000004` in a pressure-advance box. The precisions are the React ones.
 *
 * Returns an empty object unless every input it needs is a real number, so a half-filled
 * form leaves the output field alone rather than overwriting it with NaN.
 */
export type AutoCompute = (inputs: Record<string, number | null>) => Record<string, number>;

/** Every named input present and a real number. */
function have(inputs: Record<string, number | null>, ...keys: string[]): boolean {
	return keys.every((k) => typeof inputs[k] === 'number' && !Number.isNaN(inputs[k]));
}

/** Round to the step's own precision. See AUTO_COMPUTE's comment on why that is a contract. */
function at(value: number, digits: number): number {
	return Number(value.toFixed(digits));
}

export const AUTO_COMPUTE: Partial<Record<CalibrationStepType, AutoCompute>> = {
	volumetric_speed(i): Record<string, number> {
		if (!have(i, 'start_speed', 'step_size', 'measured_height')) return {};
		return { max_volumetric_speed: at(i.start_speed! + i.measured_height! * i.step_size!, 2) };
	},
	pressure_advance(i): Record<string, number> {
		if (!have(i, 'pa_step_a', 'measured_height_b')) return {};
		return { pressure_advance: at(i.pa_step_a! * i.measured_height_b!, 4) };
	},
	retraction(i): Record<string, number> {
		if (!have(i, 'start_retract', 'measured_height', 'factor')) return {};
		return { retraction_length: at(i.start_retract! + i.measured_height! * i.factor!, 5) };
	},
	tolerance(i): Record<string, number> {
		if (!have(i, 'test_size', 'measured_size')) return {};
		return { tolerance_offset: at(i.test_size! - i.measured_size!, 3) };
	}
};

/**
 * The nine steps in OrcaSlicer wiki order -- the order the wizard walks and the sidebar lists.
 * Taken from the backend enum's declaration order (spoolman/api/v1/calibration_models.py:16-25),
 * which is the same order and is the one both clients must agree on.
 */
export const WIZARD_STEP_ORDER: CalibrationStepType[] = [
	'temperature',
	'volumetric_speed',
	'pressure_advance',
	'flow_rate',
	'retraction',
	'tolerance',
	'cornering',
	'input_shaping',
	'vfa'
];
