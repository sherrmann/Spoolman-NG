/**
 * Calibration API access (#123), for the endpoints under `/api/v1/calibration`.
 *
 * Its own module rather than more of ./api.ts: that file serves the pages sharing this fork's
 * inventory aggregates, while calibration is a self-contained feature with its own entity
 * pair. Built on the same upstream `$lib/api/http` helpers, so base-URL resolution, the
 * x-total-count header and the 401 forward-auth reload are handled once.
 */
import { getJson, getList, patchJson, postJson, deleteResource } from '$lib/api/http';
import type { CalibrationSession, CalibrationStepResult, SessionBody, StepBody } from './calibrationTypes';

type Json = Record<string, unknown>;

function mapStep(s: Json): CalibrationStepResult {
	return {
		id: Number(s.id),
		sessionId: Number(s.session_id),
		stepType: s.step_type as CalibrationStepResult['stepType'],
		inputs: (s.inputs as Record<string, unknown> | undefined) ?? undefined,
		outputs: (s.outputs as Record<string, unknown> | undefined) ?? undefined,
		selectedValues: (s.selected_values as Record<string, unknown> | undefined) ?? undefined,
		notes: s.notes == null ? undefined : String(s.notes),
		confidence: s.confidence == null ? undefined : String(s.confidence),
		recordedAt: String(s.recorded_at)
	};
}

function mapSession(s: Json): CalibrationSession {
	return {
		id: Number(s.id),
		registered: String(s.registered),
		// Kept as a string to match ForkFilament.id everywhere else in this client.
		filamentId: String(s.filament_id),
		status: s.status as CalibrationSession['status'],
		startedAt: s.started_at == null ? undefined : String(s.started_at),
		completedAt: s.completed_at == null ? undefined : String(s.completed_at),
		printerName: s.printer_name == null ? undefined : String(s.printer_name),
		nozzleDiameter: s.nozzle_diameter == null ? undefined : Number(s.nozzle_diameter),
		notes: s.notes == null ? undefined : String(s.notes),
		steps: ((s.steps as Json[] | undefined) ?? []).map(mapStep)
	};
}

/**
 * Convert a filament id to the integer the wire expects.
 *
 * Guarded exactly as ./orderBody's toWireLine is, and for the same reason: a bare `Number(...)`
 * on an id that does not round-trip would attach the session to a DIFFERENT filament rather
 * than fail, and CockroachDB ids exceed the range JS numbers represent exactly.
 */
export function toWireFilamentId(filamentId: string): number {
	const id = Number(filamentId);
	if (!Number.isSafeInteger(id) || String(id) !== filamentId.trim()) {
		throw new Error(`Filament id ${filamentId} cannot be sent as an integer without losing precision.`);
	}
	return id;
}

/** Sessions for one filament. */
export async function listSessions(filamentId: string, signal?: AbortSignal): Promise<CalibrationSession[]> {
	const page = await getList(
		'/calibration/session',
		{ filament_id: String(toWireFilamentId(filamentId)) },
		signal
	);
	return (page.items as Json[]).map(mapSession);
}

export async function getSession(id: number, signal?: AbortSignal): Promise<CalibrationSession> {
	return mapSession(await getJson<Json>(`/calibration/session/${id}`, {}, signal));
}

export async function createSession(
	filamentId: string,
	body: Omit<SessionBody, 'filament_id'> = {}
): Promise<CalibrationSession> {
	return mapSession(
		await postJson<Json>('/calibration/session', {
			...body,
			filament_id: toWireFilamentId(filamentId)
		})
	);
}

export async function updateSession(id: number, body: SessionBody): Promise<CalibrationSession> {
	return mapSession(await patchJson<Json>(`/calibration/session/${id}`, body));
}

/** Deleting a session cascades to every step recorded in it. */
export async function deleteSession(id: number): Promise<void> {
	await deleteResource(`/calibration/session/${id}`);
}

export async function addStep(sessionId: number, body: StepBody): Promise<CalibrationStepResult> {
	return mapStep(await postJson<Json>(`/calibration/session/${sessionId}/step`, body));
}

export async function updateStep(stepId: number, body: StepBody): Promise<CalibrationStepResult> {
	return mapStep(await patchJson<Json>(`/calibration/step/${stepId}`, body));
}

export async function deleteStep(stepId: number): Promise<void> {
	await deleteResource(`/calibration/step/${stepId}`);
}
