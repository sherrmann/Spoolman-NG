import { apiFetch } from "./authReloadHandler";
import { getAPIURL } from "./url";

// Client helpers for the data export (#95) and import (#55) endpoints.

export type ExportEntity = "vendors" | "filaments" | "spools";
export type ImportEntity = "vendor" | "filament" | "spool";
export type DataFormat = "csv" | "json";
export type ImportMode = "create" | "upsert" | "skip_existing";
export type SlicerFormat = "prusa" | "orca" | "cura";

const SLICER_EXTENSIONS: Record<SlicerFormat, string> = {
  prusa: "ini",
  orca: "json",
  cura: "xml.fdm_material",
};

export interface ImportResult {
  created: number;
  updated: number;
  skipped: number;
  dry_run: boolean;
  errors: string[];
}

/** The plural export entity maps to its singular import counterpart. */
export function importEntityOf(entity: ExportEntity): ImportEntity {
  return entity.slice(0, -1) as ImportEntity;
}

/** Deterministic download filename, e.g. exportFilename("filaments", "csv") -> "spoolman-filaments.csv". */
export function exportFilename(entity: ExportEntity, fmt: DataFormat): string {
  return `spoolman-${entity}.${fmt}`;
}

/** True when the import applied cleanly (committed, no per-row errors). */
export function importSucceeded(result: ImportResult): boolean {
  return result.errors.length === 0;
}

/** Trigger a browser download of an exported entity in the given format. */
export async function downloadExport(entity: ExportEntity, fmt: DataFormat): Promise<void> {
  const response = await apiFetch(`${getAPIURL()}/export/${entity}?fmt=${fmt}`);
  if (!response.ok) {
    throw new Error(`Export failed (${response.status})`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = exportFilename(entity, fmt);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Extract the filename from a Content-Disposition header, or undefined if absent. Pure/testable. */
export function filenameFromContentDisposition(header: string | null): string | undefined {
  if (!header) {
    return undefined;
  }
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  return match ? decodeURIComponent(match[1]) : undefined;
}

/** Trigger a browser download of a single filament's native slicer profile (#76). */
export async function downloadSlicerProfile(filamentId: number, slicer: SlicerFormat): Promise<void> {
  const response = await apiFetch(`${getAPIURL()}/export/filament/${filamentId}/slicer?slicer=${slicer}`);
  if (!response.ok) {
    throw new Error(`Slicer export failed (${response.status})`);
  }
  const blob = await response.blob();
  const filename =
    filenameFromContentDisposition(response.headers.get("content-disposition")) ??
    `filament-${filamentId}.${SLICER_EXTENSIONS[slicer]}`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Record filament consumed on a spool via PUT /spool/{id}/use (the 3MF import apply step, #105). */
export async function applySpoolUsage(spoolId: number, useWeight: number): Promise<void> {
  const response = await apiFetch(`${getAPIURL()}/spool/${spoolId}/use`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ use_weight: useWeight }),
  });
  if (!response.ok) {
    throw new Error(`Use failed for spool ${spoolId} (${response.status})`);
  }
}

/** POST a raw CSV/JSON body to the import endpoint and return the result summary. */
export async function importData(
  entity: ImportEntity,
  fmt: DataFormat,
  mode: ImportMode,
  dryRun: boolean,
  body: string,
): Promise<ImportResult> {
  const params = new URLSearchParams({ fmt, mode, dry_run: String(dryRun) });
  const response = await apiFetch(`${getAPIURL()}/import/${entity}?${params.toString()}`, {
    method: "POST",
    headers: { "Content-Type": fmt === "csv" ? "text/csv" : "application/json" },
    body,
  });
  if (!response.ok) {
    let message = `Import failed (${response.status})`;
    try {
      message = (await response.json()).message ?? message;
    } catch {
      // Non-JSON error body; keep the status-based message.
    }
    throw new Error(message);
  }
  return response.json();
}
