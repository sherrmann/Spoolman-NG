// Parse the payload of a scanned Spoolman label back into an entity reference.
// Mirrors the forms produced by the QR generator (lib/labels/qr.ts):
//   scheme → WEB+SPOOLMAN:S-<id> / F-<id> / L-<id>           (compact custom URI)
//   url    → <base_url>/{spool,filament,location}/show/<id>  (opens in a browser)
// `S`/`spool` codes resolve to a spool, `F`/`filament` to a filament, `L`/`location`
// to a location. Anything that isn't a Spoolman code returns null, so unrelated
// codes in view are simply ignored.
//
// Spoolman NG fork addition: the `l`/`location` forms. This module is the other half
// of the label designer's location kind -- without it the Svelte client could PRINT a
// location label and then silently ignore it when scanned. The two must be widened
// together, and both match what this fork's React client already emits and parses
// (client/src/utils/scan.ts).

const SCHEME_RE = /^web\+spoolman:(?<kind>[sfl])-(?<id>[0-9]+)$/i;
const URL_RE = /^https?:\/\/[^/]+(?:\/[^/]+)*\/(?<kind>spool|filament|location)\/show\/(?<id>[0-9]+)\/?$/i;

/** A scanned Spoolman code resolved to the entity it points at. */
export interface ScannedRef {
	kind: 'spool' | 'filament' | 'location';
	id: number;
}

/**
 * Normalise the `kind` capture (`s`/`f`/`l` or the long spellings) to an entity kind.
 *
 * A switch, not the `startsWith('f') ? filament : spool` test this replaces: with a third
 * kind that test silently resolved every scanned location label to a SPOOL of the same id,
 * which is worse than ignoring it -- it opens a real but wrong record.
 */
function normaliseKind(raw: string): ScannedRef['kind'] {
	switch (raw.toLowerCase()[0]) {
		case 'f':
			return 'filament';
		case 'l':
			return 'location';
		default:
			return 'spool';
	}
}

/** Extract the entity reference from a scanned code, or null if it isn't a Spoolman code. */
export function parseSpoolCode(raw: string): ScannedRef | null {
	const text = raw.trim();
	const match = SCHEME_RE.exec(text) ?? URL_RE.exec(text);
	if (!match?.groups) return null;
	const id = Number(match.groups.id);
	if (!Number.isSafeInteger(id)) return null;
	return { kind: normaliseKind(match.groups.kind), id };
}
