/**
 * Which columns the Library's flat list shows, in what order and how wide (#412 step 5).
 *
 * Nothing stored means upstream's own row, untouched: the fork's cell renderer is only used once
 * the user has changed something, so an install that never opens the column manager keeps the
 * row upstream ships and keeps improving. Reset goes back to that by forgetting the stored
 * configuration, not by storing one that happens to look like it.
 *
 * A layout preference, so it lives in localStorage like the list width, not in the URL.
 */

export const COLUMNS_KEY = 'spoolman-ng-library-columns';

/** Narrower than this and a column's header and handle stop being usable. */
export const MIN_WIDTH = 40;
export const MAX_WIDTH = 600;

/** The column that takes whatever width is left; its stored width is its minimum. */
export const FLEX_COLUMN = 'name';

export interface ColumnsConfig {
	order: string[];
	hidden: string[];
	widths: Record<string, number>;
}

/** The columns upstream's row shows, in its order: what a fresh configuration starts from. */
export const UPSTREAM_COLUMNS = ['id', 'swatch', 'name', 'progress', 'remaining', 'location'];

/**
 * The order to show columns in: the saved order for columns that still exist, then any column
 * the saved order has never heard of (a new built-in one, or an extra field added since) in
 * catalogue order. Ids the catalogue no longer has, such as a deleted extra field, drop out.
 */
export function effectiveOrder(saved: readonly string[], catalogue: readonly string[]): string[] {
	const known = new Set(catalogue);
	const seen = new Set<string>();
	const out: string[] = [];
	for (const id of saved) {
		if (known.has(id) && !seen.has(id)) {
			out.push(id);
			seen.add(id);
		}
	}
	for (const id of catalogue) if (!seen.has(id)) out.push(id);
	return out;
}

/** The configuration a first change starts from: upstream's columns shown, everything else hidden. */
export function initialConfig(catalogue: readonly string[]): ColumnsConfig {
	const shown = new Set(UPSTREAM_COLUMNS);
	return {
		order: effectiveOrder(UPSTREAM_COLUMNS, catalogue),
		hidden: catalogue.filter((id) => !shown.has(id)),
		widths: {}
	};
}

/**
 * A configuration against today's catalogue, ready to change and save: every column in the
 * order, and any column it has never seen (an extra field added since) explicitly hidden, so
 * saving it does not make that column appear and switching it on works. Null (nothing stored)
 * starts from upstream's row.
 */
export function normaliseConfig(config: ColumnsConfig | null, catalogue: readonly string[]): ColumnsConfig {
	const c = config ?? initialConfig(catalogue);
	const seen = new Set([...c.order, ...c.hidden]);
	const unseen = catalogue.filter((id) => !seen.has(id) && id !== FLEX_COLUMN);
	const hidden = [...c.hidden, ...unseen].filter((id) => id !== FLEX_COLUMN);
	return { ...c, order: effectiveOrder(c.order, catalogue), hidden };
}

/**
 * The columns to render, in order. A column the saved configuration has never seen is hidden:
 * a new extra field should not appear in everyone's list uninvited. The name is always shown,
 * whatever a stored configuration says, as the one column that tells the rows apart.
 */
export function visibleColumns(config: ColumnsConfig, catalogue: readonly string[]): string[] {
	const hidden = new Set(config.hidden);
	const seenBefore = new Set([...config.order, ...config.hidden]);
	return effectiveOrder(config.order, catalogue).filter(
		(id) => id === FLEX_COLUMN || (seenBefore.has(id) && !hidden.has(id))
	);
}

export function clampWidth(width: number): number {
	if (!Number.isFinite(width)) return MIN_WIDTH;
	return Math.round(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width)));
}

/** Move a column one place up (-1) or down (+1) among `order`; out of range is a no-op. */
export function moveColumn(order: readonly string[], id: string, delta: -1 | 1): string[] {
	const i = order.indexOf(id);
	const j = i + delta;
	if (i < 0 || j < 0 || j >= order.length) return [...order];
	const out = [...order];
	[out[i], out[j]] = [out[j], out[i]];
	return out;
}

/**
 * The grid template for the visible columns. Every column is a fixed width (its stored one, or
 * its default) except the name, which takes the remaining space with its width as a minimum.
 */
export function gridTemplate(
	visible: readonly string[],
	widths: Record<string, number>,
	defaults: Record<string, number>
): string {
	return visible
		.map((id) => {
			const w = widths[id] ?? defaults[id] ?? 100;
			return id === FLEX_COLUMN ? `minmax(${w}px, 1fr)` : `${w}px`;
		})
		.join(' ');
}

/** Horizontal gap between columns, and padding around them, as the header and rows lay them out. */
export const COLUMN_GAP = 9;
export const ROW_PADDING = 14;

/**
 * The narrowest a row of these columns can be: every column at its width (the name at its
 * minimum), plus the gaps between them, the row's padding and its 2px selection border.
 */
export function minGridWidth(
	visible: readonly string[],
	widths: Record<string, number>,
	defaults: Record<string, number>
): number {
	const columns = visible.reduce((sum, id) => sum + (widths[id] ?? defaults[id] ?? 100), 0);
	return columns + COLUMN_GAP * Math.max(0, visible.length - 1) + 2 * ROW_PADDING + 2;
}

/** A stored configuration, or null (upstream's row) for anything that is not one. */
export function parseStoredColumns(raw: string | null): ColumnsConfig | null {
	if (!raw) return null;
	try {
		const parsed: unknown = JSON.parse(raw);
		if (typeof parsed !== 'object' || parsed === null) return null;
		const { order, hidden, widths } = parsed as Record<string, unknown>;
		const strings = (v: unknown) => Array.isArray(v) && v.every((s) => typeof s === 'string');
		if (!strings(order) || !strings(hidden)) return null;
		const cleanWidths: Record<string, number> = {};
		if (typeof widths === 'object' && widths !== null) {
			for (const [id, w] of Object.entries(widths)) {
				if (typeof w === 'number' && Number.isFinite(w)) cleanWidths[id] = clampWidth(w);
			}
		}
		return { order: order as string[], hidden: hidden as string[], widths: cleanWidths };
	} catch {
		return null;
	}
}
