/**
 * Scan payloads this client recognises beyond the entity codes (#97b, #132).
 *
 * `$lib/utils/spoolCode` handles Spoolman's own entity codes. These two are the cases that sit
 * either side of it: a reserved sentinel that means something to Spoolman but names no entity,
 * and a manufacturer barcode that means nothing to Spoolman at all but should still do
 * something useful rather than being dropped on the floor.
 *
 * Ported from client/src/utils/scan.ts, which had both under test already.
 */

/**
 * The reserved "clear this spool" payload (#132).
 *
 * Not an entity code -- it names no id. It exists so that separate integrations (a barcode
 * scanner feeding a printer, an ESPHome bridge, a label taped to the bench) can agree on ONE
 * value for "nothing is loaded now" instead of each inventing their own. The in-app scanner
 * recognises it so the scan is acknowledged rather than silently ignored, which is the whole
 * difference between a convention and a coincidence.
 */
export const CLEAR_PAYLOAD = 'WEB+SPOOLMAN:CLEAR';

/** Whether a scan is the reserved clear sentinel. Case-insensitive, like the entity codes. */
export function isClearScan(raw: string): boolean {
	return raw.trim().toLowerCase() === CLEAR_PAYLOAD.toLowerCase();
}

/**
 * Lengths a retail barcode comes in: EAN-8, UPC-A and UPC-E (both 12 digits once expanded),
 * EAN-13, and GTIN-14.
 */
const RETAIL_BARCODE_LENGTHS = new Set([8, 12, 13, 14]);

/**
 * Whether a scan that is NOT a Spoolman code looks like a manufacturer retail barcode (#97b).
 *
 * Deliberately a shape test, not a checksum: the point is to decide whether looking the value
 * up as an article number is worth a round trip, and a mis-scanned digit should still reach the
 * lookup (where it simply finds nothing) rather than being rejected here as malformed. A false
 * positive costs one query; a false negative silently drops a scan the user meant.
 */
export function looksLikeRetailBarcode(raw: string): boolean {
	const value = raw.trim();
	return /^[0-9]+$/.test(value) && RETAIL_BARCODE_LENGTHS.has(value.length);
}
