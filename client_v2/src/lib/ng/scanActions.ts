/**
 * What the scanner does with a scan, beyond upstream's navigate-to-entity (#84 / #97b / #132).
 *
 * Upstream's QrScannerModal already resolves a Spoolman entity code and navigates to it. This
 * module handles the three cases it has no notion of, and returns an EFFECT describing what
 * should happen rather than performing it: navigation, toasts and modals all belong to the
 * component, and keeping them out of here is what lets the decision logic be tested without a
 * camera. `decideScan` in ./scanMove is the same idea one level down.
 *
 * Order matters and is not arbitrary. Every scan is offered to all three paths, so they must
 * not overlap: the CLEAR sentinel is checked first because it is a fixed string that names no
 * entity; entity codes next; and a retail barcode only ever considered for a scan the entity
 * parser rejected. ./scanCodes' tests pin that these three cannot claim the same input.
 */
import { parseSpoolCode } from '$lib/utils/spoolCode';
import { getJson } from '$lib/api/http';
import { decideScan, type ScanAction, type ScanOutcome } from './scanMove';
import { isClearScan, looksLikeRetailBarcode } from './scanCodes';

/** What the scanner component should do about a scan. */
export type ScanEffect =
	/** Show a message and close; nothing else to do. */
	| { kind: 'acknowledge'; message: string }
	/** An outcome from the move state machine, for the component to render or act on. */
	| { kind: 'outcome'; outcome: ScanOutcome }
	/** A retail barcode matched a filament: offer to add a spool of it. */
	| { kind: 'add_spool'; filamentId: string }
	/** A retail barcode matched nothing: offer to create a filament remembering it. */
	| { kind: 'unknown_barcode'; code: string }
	/** The barcode lookup itself failed. */
	| { kind: 'lookup_failed' }
	/** Not ours; keep scanning. */
	| { kind: 'ignore' };

/**
 * Look a retail barcode up as a filament article number.
 *
 * The term is quoted so the backend's `article_number` filter matches EXACTLY rather than as a
 * substring -- an unquoted `12345678` would also match `123456789`, which is a different
 * product. Same quoting the React client uses.
 */
async function findByArticleNumber(code: string, signal?: AbortSignal): Promise<string | null> {
	const rows = await getJson<{ id: number | string }[]>('/filament', { article_number: `"${code}"` }, signal);
	return rows.length > 0 ? String(rows[0].id) : null;
}

/**
 * Decide what a raw scan means.
 *
 * @param raw     Exactly what the scanner read.
 * @param action  'open' to navigate, 'move' for the two-scan relocate flow.
 * @param heldSpoolId The spool captured earlier in move mode, or null.
 * @param clearMessage The localized text for the CLEAR sentinel, passed in so this module
 *                     stays free of the message runtime and remains unit-testable.
 */
export async function handleScan(
	raw: string,
	action: ScanAction,
	heldSpoolId: number | null,
	clearMessage: string,
	signal?: AbortSignal
): Promise<ScanEffect> {
	// A fixed sentinel that names no entity (#132). Spoolman itself holds no "active spool", so
	// in-app this is purely an acknowledgement -- the printer or Moonraker integration is what
	// actually clears anything. Saying so is the point: silently ignoring a code that other
	// integrations treat as meaningful is what makes a convention feel broken.
	if (isClearScan(raw)) return { kind: 'acknowledge', message: clearMessage };

	const ref = parseSpoolCode(raw);
	if (ref !== null) return { kind: 'outcome', outcome: decideScan(action, heldSpoolId, ref) };

	// Not a Spoolman code. In OPEN mode a retail barcode is worth a lookup; in move mode it is
	// noise, and interrupting a half-finished move with a filament dialog would lose the held
	// spool.
	if (action === 'open' && looksLikeRetailBarcode(raw)) {
		try {
			const filamentId = await findByArticleNumber(raw.trim(), signal);
			return filamentId !== null
				? { kind: 'add_spool', filamentId }
				: { kind: 'unknown_barcode', code: raw.trim() };
		} catch {
			return { kind: 'lookup_failed' };
		}
	}

	return { kind: 'ignore' };
}
