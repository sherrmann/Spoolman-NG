/**
 * The SpoolmanDB catalogue fields on a filament (#91, #415 step 1): what the spool is made of,
 * the surface finish, a visual pattern, and whether it is translucent or glows.
 *
 * They live on the filament view model under `ng` (see `Filament.ng` in `lib/types.ts`), so the
 * cache, live updates and the inspector's saver carry them like any other field, and upstream's
 * mapping code only has to hand over to this file. Every field is null when unknown; for the two
 * booleans `false` is information ("not translucent") and is kept distinct from null.
 *
 * See docs/design/filament-parity.md.
 */

// Structural, not `$lib/api/http`'s `Json`: this file is imported by `lib/types.ts`, and
// staying free of runtime imports keeps it safe to import from there.
type Json = Record<string, unknown>;

export const SPOOL_TYPES = ['plastic', 'cardboard', 'metal'] as const;
export const FINISHES = ['matte', 'glossy'] as const;
export const PATTERNS = ['marble', 'sparkle'] as const;

export type SpoolType = (typeof SPOOL_TYPES)[number];
export type Finish = (typeof FINISHES)[number];
export type Pattern = (typeof PATTERNS)[number];

/** The five SpoolmanDB catalogue fields, which the inspector edits. */
export interface CatalogueFields {
	spoolType: SpoolType | null;
	finish: Finish | null;
	pattern: Pattern | null;
	translucent: boolean | null;
	glow: boolean | null;
}

export type CatalogueKey = keyof CatalogueFields;

/**
 * Everything this fork reads off a filament that upstream's view model does not carry: the
 * catalogue fields, and whether it has a reference photo (#415 step 2). `hasImage` is read-only
 * here; the photo has endpoints of its own (see filamentImage.ts).
 */
export interface FilamentNg extends CatalogueFields {
	hasImage: boolean;
}

export const EMPTY_FILAMENT_NG: FilamentNg = {
	spoolType: null,
	finish: null,
	pattern: null,
	translucent: null,
	glow: null,
	hasImage: false
};

function oneOf<T extends string>(allowed: readonly T[], v: unknown): T | null {
	return typeof v === 'string' && (allowed as readonly string[]).includes(v) ? (v as T) : null;
}

function bool(v: unknown): boolean | null {
	return typeof v === 'boolean' ? v : null;
}

/** The catalogue fields of a filament as the API returns it. Anything unexpected reads as unknown. */
export function mapFilamentNg(f: Json): FilamentNg {
	return {
		spoolType: oneOf(SPOOL_TYPES, f.spool_type),
		finish: oneOf(FINISHES, f.finish),
		pattern: oneOf(PATTERNS, f.pattern),
		translucent: bool(f.translucent),
		glow: bool(f.glow),
		hasImage: f.has_image === true
	};
}

const API_NAMES: Record<CatalogueKey, string> = {
	spoolType: 'spool_type',
	finish: 'finish',
	pattern: 'pattern',
	translucent: 'translucent',
	glow: 'glow'
};

/**
 * The API body for a patch that may carry `ng`. Only the fields present in `patch.ng` are sent,
 * so saving one field never overwrites another; null is sent as null, which clears it.
 */
export function filamentNgPatchToApi(patch: { ng?: Partial<CatalogueFields> }): Json {
	const out: Json = {};
	if (!patch.ng) return out;
	for (const [key, api] of Object.entries(API_NAMES) as [CatalogueKey, string][]) {
		if (key in patch.ng) out[api] = patch.ng[key] ?? null;
	}
	return out;
}

/**
 * The catalogue fields to send when creating a filament from a SpoolmanDB entry. Only values the
 * API accepts are copied, so an entry with a value this server does not know still imports.
 *
 * Translucent and glow are copied only when true: the catalogue's model defaults both to false
 * and TigerTag entries leave them out, so a false there cannot be told from "not recorded", and
 * storing it would claim "not translucent" where nothing is known. The classic client does the
 * same (`client/src/pages/filaments/create.tsx`).
 */
export function catalogueFromExternal(ext: object): Json {
	const ng = mapFilamentNg(ext as Json);
	const out: Json = {};
	for (const [key, api] of Object.entries(API_NAMES) as [CatalogueKey, string][]) {
		const v = ng[key];
		if (v === null || v === false) continue;
		out[api] = v;
	}
	return out;
}

/**
 * The catalogue fields of an existing filament, to start a copy of it from: the duplicate flow
 * carries them, as the classic client's clone does. Undefined when the filament has none mapped.
 */
export function catalogueFieldsOf(f: FilamentNg | undefined): CatalogueFields | undefined {
	if (!f) return undefined;
	return {
		spoolType: f.spoolType,
		finish: f.finish,
		pattern: f.pattern,
		translucent: f.translucent,
		glow: f.glow
	};
}

/**
 * The catalogue fields to send when creating a filament from the new-filament form. Unknown
 * (null) is left out, which the server stores as unknown anyway. Unlike
 * {@link catalogueFromExternal}, `false` is sent: here it is an answer someone chose, or copied
 * from a filament where it was stored.
 */
export function catalogueForCreate(ng: Partial<CatalogueFields> | undefined): Json {
	const out: Json = {};
	if (!ng) return out;
	for (const [key, api] of Object.entries(API_NAMES) as [CatalogueKey, string][]) {
		const v = ng[key];
		if (v !== null && v !== undefined) out[api] = v;
	}
	return out;
}
