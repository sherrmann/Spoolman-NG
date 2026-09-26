/**
 * Reading a sliced 3MF project and matching its filaments to spools (#414 step 2). Ported from
 * the classic client's `utils/threeMfImport.ts`; see docs/design/import-export.md.
 *
 * Bambu Studio and OrcaSlicer write `Metadata/slice_info.config` into a sliced project (a zip).
 * It lists, per plate, each filament's type, colour and the grams it used. This module sums that
 * per filament across plates and suggests a spool for each; recording the usage is the caller's.
 *
 * Differences from the classic module: it reads the Svelte client's view model, and its errors
 * carry a code, so the page can show them translated rather than as fixed English.
 */
import { strFromU8, unzipSync } from 'fflate';
import type { Spool } from '$lib/types';
import type { ForkFilament } from '$lib/ng/types';

export interface ThreeMfFilament {
	/** The filament's id within the project (its AMS slot); stable across plates. */
	key: string;
	/** Material type, e.g. "PLA". */
	type?: string;
	/** Colour as #RRGGBB, upper case, alpha dropped; undefined when unknown. */
	colorHex?: string;
	/** Grams used, summed across every plate. */
	usedWeight: number;
}

export type ThreeMfErrorCode = 'invalid_file' | 'no_slice_info';

/** A file that cannot be read as a sliced project; `code` says why. */
export class ThreeMfError extends Error {
	constructor(readonly code: ThreeMfErrorCode) {
		super(code);
		this.name = 'ThreeMfError';
	}
}

const SLICE_INFO_PATH = 'Metadata/slice_info.config';

/** A 3MF colour (#RRGGBB, #RRGGBBAA, with or without the #) as #RRGGBB; undefined if too short. */
export function normalizeHex(color: string | null | undefined): string | undefined {
	if (!color) return undefined;
	const hex = color.replace(/^#/, '');
	if (hex.length < 6) return undefined;
	return `#${hex.slice(0, 6).toUpperCase()}`;
}

/**
 * Per-filament usage from a slice_info.config, summed across plates. Filaments that used nothing
 * are left out. Uses `getElementsByTagName`, which the browser's DOM and the tests' XML parser
 * both provide.
 */
export function parseSliceInfo(xml: string): ThreeMfFilament[] {
	const doc = new DOMParser().parseFromString(xml, 'application/xml');
	if (doc.getElementsByTagName('parsererror').length > 0) throw new ThreeMfError('invalid_file');
	const byId = new Map<string, ThreeMfFilament>();
	for (const el of Array.from(doc.getElementsByTagName('filament'))) {
		const id = el.getAttribute('id') ?? String(byId.size + 1);
		const usedWeight = Number.parseFloat(el.getAttribute('used_g') ?? '0') || 0;
		const existing = byId.get(id);
		if (existing) {
			existing.usedWeight += usedWeight;
		} else {
			byId.set(id, {
				key: id,
				type: el.getAttribute('type') ?? undefined,
				colorHex: normalizeHex(el.getAttribute('color')),
				usedWeight
			});
		}
	}
	return Array.from(byId.values()).filter((f) => f.usedWeight > 0);
}

/** Unzip a .3mf and read its per-filament usage. */
export function parseThreeMf(bytes: Uint8Array): ThreeMfFilament[] {
	let files: Record<string, Uint8Array>;
	try {
		files = unzipSync(bytes);
	} catch {
		throw new ThreeMfError('invalid_file');
	}
	const entry = files[SLICE_INFO_PATH];
	if (!entry) throw new ThreeMfError('no_slice_info');
	return parseSliceInfo(strFromU8(entry));
}

/** A spool's colour for matching: its filament's first colour. */
export function spoolPrimaryHex(spool: Spool, filaments: ForkFilament[]): string | undefined {
	return normalizeHex(filaments.find((f) => f.id === spool.filamentId)?.colors[0]);
}

/**
 * The suggested spool for a project filament: one of exactly the same colour, preferring one of
 * the same material too. Undefined when no spool has that colour; the user then picks one, since
 * a project's colours will not always match a spool in stock.
 */
export function autoMatchSpoolId(
	tmf: ThreeMfFilament,
	spools: Spool[],
	filaments: ForkFilament[]
): number | undefined {
	if (!tmf.colorHex) return undefined;
	const colorMatches = spools.filter((s) => spoolPrimaryHex(s, filaments) === tmf.colorHex);
	if (colorMatches.length === 0) return undefined;
	const type = tmf.type?.toLowerCase();
	const withMaterial = type
		? colorMatches.find(
				(s) => (filaments.find((f) => f.id === s.filamentId)?.material ?? '').toLowerCase() === type
			)
		: undefined;
	return (withMaterial ?? colorMatches[0]).id;
}
