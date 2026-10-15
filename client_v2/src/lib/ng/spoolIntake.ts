/**
 * Scan-to-Spool photo intake (#361, #418): the request to the vision model, and the maths
 * between its answer and the Add-spools form. Ported from the classic client's
 * `components/photoIntake.tsx` and `utils/queryAI.ts`.
 *
 * The photo is downscaled in the browser, sent as base64, analysed in the server's memory and
 * thrown away -- nothing here stores it. Matching is library-first: a filament the user already
 * owns just gains a spool; a SpoolmanDB entry opens the same form with that entry chosen (the
 * form creates the filament and the spool together, on confirmation); and the raw extraction
 * opens a blank new-filament form carrying what was read.
 */
import { getJson, HttpError, postJson } from '$lib/api/http';
import type { ExternalFilament } from '$lib/api/external';
import { fitWithin } from './filamentImage';

/** The longest edge sent to the model. Bigger buys no extra legibility and risks the 413. */
export const MAX_EDGE = 1568;
export const JPEG_QUALITY = 0.85;
/** The only types the server accepts (`_ALLOWED_IMAGE_MIMES`). */
const ALLOWED_MIMES = ['image/jpeg', 'image/png', 'image/webp'];

export interface SpoolIntakeExtraction {
	vendor: string | null;
	name: string | null;
	material: string | null;
	color_hex: string | null;
	weight_g: number | null;
	spool_weight_g: number | null;
	diameter_mm: number | null;
	extruder_temp_c: number | null;
	bed_temp_c: number | null;
	lot_nr: string | null;
	article_number: string | null;
	confidence: string | null;
}

export interface SpoolIntakeMatch {
	kind: 'library' | 'catalog';
	/** Library matches only. */
	filament_id?: number;
	/** Catalogue matches only: the SpoolmanDB id. */
	external_id?: string;
	vendor: string | null;
	name: string | null;
	material: string | null;
	match_percent: number;
}

export interface SpoolIntakeResult {
	extraction: SpoolIntakeExtraction;
	matches: { library: SpoolIntakeMatch[]; catalog: SpoolIntakeMatch[] };
}

/** Why an extraction failed, one value per HTTP status that needs its own wording. */
export type IntakeFailure =
	/** 404 -- the feature is off server-side, whatever the settings said. */
	| 'disabled'
	/** 409 -- no endpoint and model configured yet. */
	| 'unconfigured'
	/** 413 -- the image survived downscaling and is still too big. */
	| 'too_large'
	/** 400 -- not an image the server can read. */
	| 'bad_image'
	/** 502, a dropped connection, anything else. */
	| 'failed';

export class IntakeError extends Error {
	constructor(readonly failure: IntakeFailure) {
		super(`Photo intake failed: ${failure}`);
		this.name = 'IntakeError';
	}
}

export function failureFor(e: unknown): IntakeFailure {
	if (!(e instanceof HttpError)) return 'failed';
	switch (e.status) {
		case 404:
			return 'disabled';
		case 409:
			return 'unconfigured';
		case 413:
			return 'too_large';
		case 400:
			return 'bad_image';
		default:
			return 'failed';
	}
}

/**
 * Send a prepared photo for extraction. Rejects with an {@link IntakeError}, or with an
 * AbortError when `signal` fired: the shared POST helper cannot cancel a request already on the
 * wire (a write that has left the browser has changed the server), so an abort means "discard
 * the answer", which is all a closed dialog needs.
 */
export async function extractFromPhoto(
	base64: string,
	mime: string,
	signal?: AbortSignal
): Promise<SpoolIntakeResult> {
	let res: SpoolIntakeResult;
	try {
		res = await postJson<SpoolIntakeResult>('/ai/spool-intake/extract', { image_base64: base64, mime });
	} catch (e) {
		if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
		throw new IntakeError(failureFor(e));
	}
	if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
	return {
		extraction: res.extraction,
		matches: { library: res.matches?.library ?? [], catalog: res.matches?.catalog ?? [] }
	};
}

/** The extraction's non-null fields in the order the classic client lists them. */
export const ROW_KEYS = [
	'vendor',
	'name',
	'material',
	'weight_g',
	'diameter_mm',
	'extruder_temp_c',
	'bed_temp_c',
	'lot_nr',
	'article_number',
	'confidence'
] as const;
export type RowKey = (typeof ROW_KEYS)[number];

export function extractionRows(extraction: SpoolIntakeExtraction): { key: RowKey; value: string }[] {
	return ROW_KEYS.filter((key) => extraction[key] !== null && extraction[key] !== undefined).map((key) => ({
		key,
		value: String(extraction[key])
	}));
}

/** One radio in the review: `lib:<filament id>`, `cat:<external id>` or `raw`. */
export interface IntakeChoice {
	value: string;
	kind: 'library' | 'catalog' | 'raw';
	vendor: string | null;
	name: string | null;
	material: string | null;
	matchPercent: number | null;
}

/** Library matches first, then catalogue, then the raw extraction. The first is the default. */
export function intakeChoices(result: SpoolIntakeResult): IntakeChoice[] {
	const out: IntakeChoice[] = [];
	for (const match of result.matches.library) {
		out.push({
			value: `lib:${match.filament_id}`,
			kind: 'library',
			vendor: match.vendor,
			name: match.name,
			material: match.material,
			matchPercent: match.match_percent
		});
	}
	for (const match of result.matches.catalog) {
		out.push({
			value: `cat:${match.external_id}`,
			kind: 'catalog',
			vendor: match.vendor,
			name: match.name,
			material: match.material,
			matchPercent: match.match_percent
		});
	}
	out.push({ value: 'raw', kind: 'raw', vendor: null, name: null, material: null, matchPercent: null });
	return out;
}

/**
 * What a new-filament form is seeded with. Strings, because that is what the form's inputs
 * hold; an empty one means "not read from the photo". `colorHex` is bare hex, as the form
 * stores colours.
 */
export interface RawIntakeDraft {
	vendorName: string;
	name: string;
	material: string;
	weight: string;
	spoolWeight: string;
	diameter: string;
	nozzleTemp: string;
	bedTemp: string;
	colorHex: string;
	articleNumber: string;
	lot: string;
}

/**
 * The seed the Add-spools modal reads. Held in the `ui` store, which is why it lives here
 * rather than beside the modal: the store is upstream's and only imports this type.
 */
export interface IntakePreset {
	/** Filled into the spool's lot field. */
	lot?: string;
	/** A SpoolmanDB entry to open the modal with already chosen. */
	external?: ExternalFilament;
	/** A blank new-filament form to open with these values in it. */
	draft?: RawIntakeDraft;
}

export type IntakeHandoff =
	| { kind: 'library'; filamentId: string; lot: string | null }
	| { kind: 'catalog'; externalId: string; lot: string | null }
	| { kind: 'raw'; draft: RawIntakeDraft };

const str = (v: string | number | null | undefined): string =>
	v === null || v === undefined ? '' : String(v);

/** The raw extraction as form values. */
export function rawDraftFrom(extraction: SpoolIntakeExtraction): RawIntakeDraft {
	return {
		vendorName: str(extraction.vendor),
		name: str(extraction.name),
		material: str(extraction.material),
		weight: str(extraction.weight_g),
		spoolWeight: str(extraction.spool_weight_g),
		diameter: str(extraction.diameter_mm),
		nozzleTemp: str(extraction.extruder_temp_c),
		bedTemp: str(extraction.bed_temp_c),
		colorHex: str(extraction.color_hex).replace(/^#/, ''),
		articleNumber: str(extraction.article_number),
		lot: str(extraction.lot_nr)
	};
}

/** Translate a chosen radio into the handoff the Add-spools modal is opened with. */
export function handoffFor(choice: string, extraction: SpoolIntakeExtraction): IntakeHandoff {
	const lot = extraction.lot_nr ? extraction.lot_nr : null;
	if (choice.startsWith('lib:')) return { kind: 'library', filamentId: choice.slice(4), lot };
	if (choice.startsWith('cat:')) return { kind: 'catalog', externalId: choice.slice(4), lot };
	return { kind: 'raw', draft: rawDraftFrom(extraction) };
}

/**
 * One SpoolmanDB entry by id, via the existing filter on `GET /external/filament`. Null when
 * the catalogue no longer has it or cannot be reached, so the caller can fall back.
 */
export async function lookupCatalogueEntry(externalId: string): Promise<ExternalFilament | null> {
	try {
		const found = await getJson<ExternalFilament[]>('/external/filament', { id: externalId });
		return found.find((e) => e.id === externalId) ?? null;
	} catch {
		return null;
	}
}

export interface PreparedPhoto {
	base64: string;
	mime: string;
	/** What was sent, for the thumbnail. */
	preview: Blob;
}

function blobToBase64(blob: Blob): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '');
		reader.onerror = () => reject(reader.error);
		reader.readAsDataURL(blob);
	});
}

/**
 * Scale the photo's longest edge to {@link MAX_EDGE} and encode it as JPEG. Downscaling is an
 * optimisation, so any failure (no `createImageBitmap`, an undecodable file) falls back to
 * sending the original -- the server then decides whether it can read it.
 */
export async function preparePhoto(file: File): Promise<PreparedPhoto> {
	try {
		const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
		try {
			const { width, height } = fitWithin(bitmap.width, bitmap.height, MAX_EDGE);
			const canvas = document.createElement('canvas');
			canvas.width = width;
			canvas.height = height;
			const context = canvas.getContext('2d');
			if (!context) throw new Error('no canvas context');
			context.drawImage(bitmap, 0, 0, width, height);
			const blob = await new Promise<Blob>((resolve, reject) =>
				canvas.toBlob(
					(b) => (b ? resolve(b) : reject(new Error('encode failed'))),
					'image/jpeg',
					JPEG_QUALITY
				)
			);
			return { base64: await blobToBase64(blob), mime: 'image/jpeg', preview: blob };
		} finally {
			bitmap.close();
		}
	} catch {
		const mime = ALLOWED_MIMES.includes(file.type) ? file.type : 'image/jpeg';
		return { base64: await blobToBase64(file), mime, preview: file };
	}
}
