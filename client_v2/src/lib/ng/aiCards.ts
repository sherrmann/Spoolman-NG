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

// --- Read-tool result cards (#381) -------------------------------------------------------

/**
 * What a read tool's result card shows, one entry per row.
 *
 * Built only from the rows the server whitelisted out of the tool's own result
 * (spoolman/aichat.py, _CARD_FIELDS), so a card cannot show a number the tools did not
 * return. Words come in through `CardWords`, so this module stays free of the message runtime
 * and testable without it.
 */
export interface ResultRow {
	key: string;
	title: string;
	detail: string;
	value: string;
	/** A `#rrggbb` colour for the swatch, or null when the row has none or it is malformed. */
	swatch: string | null;
	/** Where the row opens in this client, or null when it has no page of its own. */
	href: string | null;
	tags: ('low_stock' | 'on_order')[];
}

export interface ResultCard {
	rows: ResultRow[];
	/** How many results the tool found beyond the rows shown. */
	more: number;
}

export interface CardWords {
	spools: (count: number) => string;
	filaments: (count: number) => string;
	outstanding: (count: number) => string;
	arrived: string;
	match: (percent: number) => string;
}

/** `1234.5` -> `1,234.5 g` in the reader's locale; null when there is no number. */
export function grams(value: unknown): string {
	return typeof value === 'number' && Number.isFinite(value) ? `${value.toLocaleString()} g` : '';
}

/** A CSS colour for a stored hex (6 or 8 digits, no `#`), or null if it is not one. */
export function swatchColour(value: unknown): string | null {
	return typeof value === 'string' && /^[0-9a-f]{6}([0-9a-f]{2})?$/i.test(value) ? `#${value}` : null;
}

const text = (value: unknown): string => (value === null || value === undefined ? '' : String(value));
const joined = (...parts: unknown[]): string => parts.map(text).filter(Boolean).join(' · ');
const count = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) ? value : 0);
const idOf = (value: unknown): number | null =>
	typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : null;

/**
 * The card for one tool event, or null when the tool has no card (or nothing to show).
 *
 * `paths` builds links so this module does not need to know the app's base path.
 */
export function resultCard(
	name: string,
	rows: Record<string, unknown>[] | undefined,
	total: number | undefined,
	words: CardWords,
	paths: { spool: (id: number) => string; filament: (id: number) => string }
): ResultCard | null {
	if (!rows || rows.length === 0) return null;
	const build = ROW_BUILDERS[name];
	if (!build) return null;
	const out = rows.map((row, i) => build(row, i, words, paths));
	const found = typeof total === 'number' && total > out.length ? total : out.length;
	return { rows: out, more: found - out.length };
}

type RowBuilder = (
	row: Record<string, unknown>,
	index: number,
	words: CardWords,
	paths: { spool: (id: number) => string; filament: (id: number) => string }
) => ResultRow;

const blank = (key: string): ResultRow => ({
	key,
	title: '',
	detail: '',
	value: '',
	swatch: null,
	href: null,
	tags: []
});

const ROW_BUILDERS: Record<string, RowBuilder> = {
	find_spools: (r, i, _w, paths) => {
		const id = idOf(r.id);
		return {
			...blank(`spool-${id ?? i}`),
			title: id ? `#${id} ${text(r.filament)}`.trim() : text(r.filament),
			detail: joined(r.material, r.location),
			value: grams(r.remaining_weight_g),
			swatch: swatchColour(r.color_hex),
			href: id ? paths.spool(id) : null
		};
	},
	find_filaments: (r, i, _w, paths) => {
		const id = idOf(r.id);
		const tags: ResultRow['tags'] = [];
		if (r.low_stock === true) tags.push('low_stock');
		if (r.on_order === true) tags.push('on_order');
		return {
			...blank(`filament-${id ?? i}`),
			title: text(r.name),
			detail: joined(r.vendor, r.material),
			value: grams(r.total_remaining_weight_g),
			swatch: swatchColour(r.color_hex),
			href: id ? paths.filament(id) : null,
			tags
		};
	},
	find_orders: (r, i, w) => ({
		...blank(`order-${idOf(r.id) ?? i}`),
		title: joined(r.shop, r.order_number) || `#${text(r.id)}`,
		detail: r.status === 'open' ? w.outstanding(count(r.outstanding_units)) : w.arrived,
		value: ''
	}),
	find_locations: (r, i, w) => ({
		...blank(`location-${idOf(r.id) ?? i}`),
		title: text(r.name),
		detail: w.spools(count(r.spool_count)),
		value: grams(r.remaining_weight_g)
	}),
	find_vendors: (r, i, w) => ({
		...blank(`vendor-${idOf(r.id) ?? i}`),
		title: text(r.name),
		detail: joined(w.filaments(count(r.filament_count)), w.spools(count(r.spool_count)))
	}),
	catalog_lookup: (r, i, w) => ({
		...blank(`catalog-${text(r.external_id) || i}`),
		title: joined(r.vendor, r.name),
		detail: text(r.material),
		value: typeof r.match_percent === 'number' ? w.match(r.match_percent) : ''
	})
};

export interface UsageBar {
	period: string;
	value: string;
	/** Bar length as a percentage of the largest period, 0-100. */
	width: number;
}

/**
 * Bars for `get_usage_stats`, oldest first, scaled to the busiest period.
 *
 * Plain numbers for a CSS bar, not a chart library: the drawer is narrow and the server caps
 * the number of periods.
 */
export function usageBars(periods: { period: string; consumed_weight: number }[] | undefined): UsageBar[] {
	if (!periods || periods.length === 0) return [];
	const max = Math.max(...periods.map((p) => (Number.isFinite(p.consumed_weight) ? p.consumed_weight : 0)));
	return periods.map((p) => {
		const weight = Number.isFinite(p.consumed_weight) ? Math.max(p.consumed_weight, 0) : 0;
		return {
			period: p.period,
			value: grams(Math.round(weight)),
			width: max > 0 ? Math.round((weight / max) * 100) : 0
		};
	});
}
