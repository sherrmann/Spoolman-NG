/**
 * Calibration domain types (#123), ported from client/src/pages/calibration/model.ts.
 *
 * These stay close to the wire shape rather than being camelCased like the rest of this
 * client's domain types, for one reason: `inputs`, `outputs` and `selected_values` are opaque
 * JSON blobs the backend stores verbatim (spoolman/api/v1/calibration.py serialises them with
 * json.dumps and never inspects them). Every key inside them is a field key from
 * ./calibrationConfig, and renaming the fields around them would invite renaming those too --
 * which would silently orphan every session already recorded by the React client.
 *
 * Ids here are plain integers, unlike filament and vendor ids elsewhere in this client (which
 * are strings, because CockroachDB ids exceed the range JS numbers represent exactly). Session
 * and step ids are ordinary serials. `filamentId` is the exception and is kept as a string to
 * match ForkFilament; ./calibrationApi guards the conversion at the one point it is sent.
 */

export type CalibrationStatus = 'planned' | 'in_progress' | 'complete' | 'archived';

/** The nine OrcaSlicer steps, in wiki order. The order is meaningful -- see WIZARD_STEP_ORDER. */
export type CalibrationStepType =
	| 'temperature'
	| 'volumetric_speed'
	| 'pressure_advance'
	| 'flow_rate'
	| 'retraction'
	| 'tolerance'
	| 'cornering'
	| 'input_shaping'
	| 'vfa';

/** One recorded step within a session. */
export interface CalibrationStepResult {
	id: number;
	sessionId: number;
	stepType: CalibrationStepType;
	/** Test setup values. Opaque to the server; keys come from ./calibrationConfig. */
	inputs?: Record<string, unknown>;
	/** Measured result values. Opaque to the server. */
	outputs?: Record<string, unknown>;
	/** The subset of outputs presented as "recommended settings". */
	selectedValues?: Record<string, unknown>;
	notes?: string;
	confidence?: string;
	recordedAt: string;
}

export interface CalibrationSession {
	id: number;
	registered: string;
	filamentId: string;
	status: CalibrationStatus;
	startedAt?: string;
	completedAt?: string;
	printerName?: string;
	nozzleDiameter?: number;
	notes?: string;
	steps: CalibrationStepResult[];
}

/** Write shape for POST/PATCH /calibration/session. */
export interface SessionBody {
	filament_id?: number;
	status?: CalibrationStatus;
	printer_name?: string | null;
	nozzle_diameter?: number | null;
	notes?: string | null;
	started_at?: string | null;
	completed_at?: string | null;
}

/**
 * Write shape for POST /calibration/session/{id}/step and PATCH /calibration/step/{id}.
 *
 * PATCH merges at the TOP level only: a field left out keeps its stored value, but a field
 * that IS present replaces its whole value. For the three JSON blobs that means a caller
 * editing one measurement must resend the entire object -- exactly the rule the order line
 * set follows (see ./orderEditBody's module comment), and for the same reason: the server
 * treats the value as one opaque unit.
 */
export interface StepBody {
	step_type?: CalibrationStepType;
	inputs?: Record<string, unknown> | null;
	outputs?: Record<string, unknown> | null;
	selected_values?: Record<string, unknown> | null;
	notes?: string | null;
	confidence?: string | null;
	recorded_at?: string;
}

/**
 * The sentinel a deliberately skipped step carries.
 *
 * A client-side convention with no backend awareness: the wizard writes
 * `outputs: { _skipped: true }` with null inputs and selected_values, and the history list
 * reads it back to show "Skipped" rather than "Incomplete". Kept identical to the React
 * client's spelling (CalibrationWizard.tsx) so sessions recorded there read correctly here
 * and vice versa -- the two clients share one database.
 */
export const SKIPPED_SENTINEL = '_skipped';

/** Whether a step was explicitly skipped rather than left unrecorded. */
export function isSkipped(step: CalibrationStepResult): boolean {
	return step.outputs?.[SKIPPED_SENTINEL] === true;
}
