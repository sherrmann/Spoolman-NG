/**
 * Turning a confirm-card's before/after maps into rows a person can read.
 *
 * The card is what stands between the assistant and your database, so what it shows is the
 * whole safeguard: an unreadable preview gets approved on trust, which is the same as no
 * preview. Three shapes, decided by which side has values:
 *
 *   create   only `after`  -- list what will exist
 *   delete   only `before` -- list what will be lost
 *   update   both          -- show only what actually changes, old struck through
 *
 * An update lists ONLY changed fields on purpose. The server sends whole objects, and a card
 * showing forty unchanged rows around the one that moved hides the very thing it exists to
 * show.
 *
 * Labels are humanised from the field key rather than translated. The React client maps each
 * key onto an existing `spool.fields.*` / `filament.fields.*` message, which is better and is
 * worth doing here too -- but paraglide compiles messages to named exports rather than a
 * lookup table, so a key-to-message map has to be written out by hand, and that is its own
 * change. Recorded here so the shortcut is visible rather than mistaken for the intent.
 */

export interface CardRow {
	label: string;
	before: string;
	after: string;
	/** Whether this row is a change, as opposed to a plain value on a create or delete. */
	changed: boolean;
}

interface CardLike {
	before: Record<string, unknown>;
	after: Record<string, unknown>;
}

/** `used_weight` -> `Used weight`. */
export function humaniseKey(key: string): string {
	const words = key.replace(/[_-]+/g, ' ').trim();
	if (!words) return key;
	return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Render one value.
 *
 * Numbers go through the locale's own formatter so a thousand reads as a thousand, but nothing
 * here guesses units: the server's `summary` line carries the sentence, and a preview that
 * invented "g" on a field that turned out to be a price would be worse than a bare number.
 */
export function formatCardValue(value: unknown, notSet: string): string {
	if (value === null || value === undefined || value === '') return notSet;
	if (typeof value === 'boolean') return value ? '✓' : '✗';
	if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : notSet;
	if (Array.isArray(value)) return value.length ? value.map(String).join(', ') : notSet;
	if (typeof value === 'object') return JSON.stringify(value);
	return String(value);
}

/**
 * The rows for one card.
 *
 * `notSet` is passed in rather than imported so this module stays free of the message runtime
 * and testable without it -- the same split the scanner's decision modules use.
 */
export function cardRows(card: CardLike, notSet = 'not set'): CardRow[] {
	const before = card.before ?? {};
	const after = card.after ?? {};
	const hasBefore = Object.keys(before).length > 0;
	const hasAfter = Object.keys(after).length > 0;

	// A create: nothing existed, so every field is simply what will be there.
	if (!hasBefore && hasAfter) {
		return Object.entries(after).map(([key, value]) => ({
			label: humaniseKey(key),
			before: '',
			after: formatCardValue(value, notSet),
			changed: false
		}));
	}

	// A delete: nothing will exist, so every field is what is about to be lost.
	if (hasBefore && !hasAfter) {
		return Object.entries(before).map(([key, value]) => ({
			label: humaniseKey(key),
			before: '',
			after: formatCardValue(value, notSet),
			changed: false
		}));
	}

	// An update. Keys are taken from `after`, since that is what the write proposes to set;
	// a key present only in `before` is not being touched.
	return Object.entries(after)
		.filter(([key, value]) => !sameValue(before[key], value))
		.map(([key, value]) => ({
			label: humaniseKey(key),
			before: formatCardValue(before[key], notSet),
			after: formatCardValue(value, notSet),
			changed: true
		}));
}

/**
 * Whether two values are the same for preview purposes.
 *
 * Compared structurally, because the server round-trips through JSON and a field holding a list
 * or an object arrives as a fresh instance every time -- reference equality would report every
 * such field as changed and bury the real edit.
 */
function sameValue(a: unknown, b: unknown): boolean {
	if (a === b) return true;
	if (a === null || a === undefined || b === null || b === undefined) return false;
	if (typeof a === 'object' || typeof b === 'object') {
		try {
			return JSON.stringify(a) === JSON.stringify(b);
		} catch {
			return false;
		}
	}
	return false;
}
