/**
 * Export, import and the inventory report's numbers (#414 step 1), over the server's
 * `/export/*` and `/import/*` endpoints. Ported from the classic client's
 * `utils/importExport.ts`; see docs/design/import-export.md.
 *
 * Downloads go through fetch rather than a link: the bearer token lives in localStorage, and an
 * `<a href>` to `/export/...` would carry no credential and be refused on an authenticated
 * install.
 */
import { API_BASE } from '$lib/api/config';
import { handleUnauthorized } from '$lib/api/auth';
import { HttpError } from '$lib/api/http';
import { authHeaders } from '$lib/ng/authToken';
import type { Spool } from '$lib/types';
import type { ForkFilament } from '$lib/ng/types';
import { materialBreakdown, totalRemainingWeight, totalValue } from '$lib/ng/analytics';

export const EXPORT_ENTITIES = ['spools', 'filaments', 'vendors'] as const;
export type ExportEntity = (typeof EXPORT_ENTITIES)[number];

export const IMPORT_ENTITIES = ['spool', 'filament', 'vendor'] as const;
export type ImportEntity = (typeof IMPORT_ENTITIES)[number];

export const IMPORT_MODES = ['create', 'upsert', 'skip_existing'] as const;
export type ImportMode = (typeof IMPORT_MODES)[number];

export type DataFormat = 'csv' | 'json';

export interface ImportResult {
	created: number;
	updated: number;
	skipped: number;
	dryRun: boolean;
	errors: string[];
}

/** The import entity for an export entity, e.g. `spools` → `spool`: the server's two spellings. */
export function importEntityFor(entity: ExportEntity): ImportEntity {
	return entity.slice(0, -1) as ImportEntity;
}

export function exportFilename(entity: ExportEntity, fmt: DataFormat): string {
	return `spoolman-${entity}.${fmt}`;
}

/** The format a picked file is in, from its extension; null when the name says neither. */
export function formatFromFilename(name: string): DataFormat | null {
	const lower = name.toLowerCase();
	if (lower.endsWith('.csv')) return 'csv';
	if (lower.endsWith('.json')) return 'json';
	return null;
}

/** Whether an import went through (or, for a dry run, would): any row error fails the whole file. */
export function importSucceeded(result: ImportResult): boolean {
	return result.errors.length === 0;
}

/** The server's answer, read defensively: a field it did not send reads as zero or empty. */
export function parseImportResult(body: unknown): ImportResult {
	const b = (body ?? {}) as Record<string, unknown>;
	const n = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
	return {
		created: n(b.created),
		updated: n(b.updated),
		skipped: n(b.skipped),
		dryRun: b.dry_run === true,
		errors: Array.isArray(b.errors) ? b.errors.map(String) : []
	};
}

async function failure(res: Response, what: string): Promise<HttpError> {
	// A read may answer a 401 with a reload, as http.ts's reads do; a write may not.
	if (res.status === 401) handleUnauthorized(res, what === 'export');
	let body: Record<string, unknown> | undefined;
	try {
		body = (await res.json()) as Record<string, unknown>;
	} catch {
		/* no body, or not JSON */
	}
	const detail = typeof body?.message === 'string' ? `: ${body.message}` : '';
	return new HttpError(`${what} → ${res.status}${detail}`, res.status, body);
}

/** Save a blob under a filename, through a temporary link. */
export function saveBlob(blob: Blob, filename: string): void {
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	a.remove();
	URL.revokeObjectURL(url);
}

/** Fetch an export with the caller's credentials and hand it to the browser as a download. */
export async function downloadExport(entity: ExportEntity, fmt: DataFormat): Promise<void> {
	const res = await fetch(`${API_BASE}/export/${entity}?fmt=${fmt}`, { headers: authHeaders() });
	if (!res.ok) throw await failure(res, 'export');
	saveBlob(await res.blob(), exportFilename(entity, fmt));
}

/** Send a file's text to the import endpoint as the raw body the server expects. */
export async function importData(
	entity: ImportEntity,
	fmt: DataFormat,
	mode: ImportMode,
	dryRun: boolean,
	body: string
): Promise<ImportResult> {
	const q = new URLSearchParams({ fmt, mode, dry_run: String(dryRun) });
	const res = await fetch(`${API_BASE}/import/${entity}?${q}`, {
		method: 'POST',
		body,
		headers: { 'Content-Type': fmt === 'csv' ? 'text/csv' : 'application/json', ...authHeaders() }
	});
	if (!res.ok) throw await failure(res, 'import');
	return parseImportResult(await res.json());
}

export interface InventoryReport {
	spoolCount: number;
	remainingWeight: number;
	value: number;
	/** Material, spool count and remaining weight, largest stock first. */
	materials: { material: string; count: number; weight: number }[];
}

/** The report's numbers, from the same helpers the home page uses, so the two always agree. */
export function inventoryReport(spools: Spool[], filaments: ForkFilament[]): InventoryReport {
	return {
		spoolCount: spools.length,
		remainingWeight: totalRemainingWeight(spools),
		value: totalValue(spools, filaments),
		materials: materialBreakdown(spools, filaments).map(([material, s]) => ({
			material,
			count: s.count,
			weight: s.weight
		}))
	};
}
