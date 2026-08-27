/**
 * Dynamic i18n lookups for calibration UI (#123).
 *
 * ./calibrationConfig deliberately dropped the React object's `label` strings (see its own
 * doc comment): a field's label, a select option's label, a step type's name and a step's
 * wizard copy all live in this fork's message catalogue instead, keyed by the field/step/value
 * itself rather than hardcoded per call site. This module is the one place that builds those
 * key strings and resolves them through `ng`, so StepEditor, CalibrationWizard, StepEditModal
 * and the calibration route all read the same labels the same way.
 *
 * Resolution follows `plural()` in ./i18n: a message id with no real translation renders as
 * its own id rather than throwing, so a lookup that finds nothing (a key genuinely missing --
 * should not happen for the 173 calibration_* keys this fork ships, but a bug is not a crash)
 * falls back to that same id instead of crashing the page.
 */
import { ng } from './i18n';
import { fieldSection, type StepConfig, type StepField } from './calibrationConfig';
import type { CalibrationStatus, CalibrationStepType } from './calibrationTypes';

type MessageFn = (inputs?: Record<string, unknown>) => string;
const byId = ng as unknown as Record<string, MessageFn | undefined>;

/** Resolve one message id, falling back to the id itself when it has no real translation. */
function resolve(id: string): string {
	const fn = byId[id];
	if (!fn) return id;
	const out = fn();
	return out === id ? id : out;
}

/** A field's label: `calibration_field_labels_{inputs|outputs}_{key}`. */
export function fieldLabel(config: StepConfig, field: StepField): string {
	return resolve(`calibration_field_labels_${fieldSection(config, field)}_${field.key}`);
}

/** A `select` field option's label: `calibration_field_labels_options_{value}`. */
export function optionLabel(value: string): string {
	return resolve(`calibration_field_labels_options_${value}`);
}

/** A step type's short name, e.g. for the wizard sidebar or a history row's tag. */
export function stepTypeLabel(stepType: CalibrationStepType): string {
	return resolve(`calibration_step_types_${stepType}`);
}

/** A session status's label. */
export function statusLabel(status: CalibrationStatus): string {
	return resolve(`calibration_status_${status}`);
}

/** A confidence value's label ('high' | 'medium' | 'low'). */
export function confidenceLabel(confidence: string): string {
	return resolve(`calibration_confidence_${confidence}`);
}

/** The wizard/drawer copy for one step: `calibration_step_copy_{stepType}_title/description`. */
export function stepCopyTitle(stepType: CalibrationStepType): string {
	return resolve(`calibration_step_copy_${stepType}_title`);
}
export function stepCopyDescription(stepType: CalibrationStepType): string {
	return resolve(`calibration_step_copy_${stepType}_description`);
}

/**
 * OrcaSlicer wiki page for each step, matching the React client's `wizardCopy.ts` (its
 * `WIKI_BASE` + per-step slug). Plain reference data, not user-facing copy, so it stays a
 * constant here rather than a message key -- there is nothing to translate.
 */
const WIKI_BASE = 'https://github.com/SoftFever/OrcaSlicer/wiki';
const WIKI_SLUGS: Record<CalibrationStepType, string> = {
	temperature: 'temp-calib',
	volumetric_speed: 'volumetric-speed-calib',
	pressure_advance: 'pressure-advance-calib',
	flow_rate: 'flow-rate-calib',
	retraction: 'retraction-calib',
	tolerance: 'tolerance-calib',
	cornering: 'cornering-calib',
	input_shaping: 'input-shaping-calib',
	vfa: 'vfa-calib'
};

export function stepWikiUrl(stepType: CalibrationStepType): string {
	return `${WIKI_BASE}/${WIKI_SLUGS[stepType]}`;
}
