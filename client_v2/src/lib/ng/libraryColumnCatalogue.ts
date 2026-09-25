/**
 * The columns the Library's flat list can show (#412 step 5): every built-in spool and filament
 * field worth a column, plus one per spool extra field. Labels are the app's own field names.
 */
import * as m from '$lib/paraglide/messages';
import type { FieldDef } from '$lib/api/fields';
import { ng } from '$lib/ng/i18n';

export interface ColumnDef {
	id: string;
	label: () => string;
	/** Default width in px; for the name column, its minimum. */
	width: number;
	/** Numbers read best right-aligned, so their units line up. */
	align?: 'right';
}

const BUILT_IN: ColumnDef[] = [
	// The first six are upstream's row, at its widths, so the starting layout fits where that
	// row fits (the list pane's default width).
	{ id: 'id', label: m['spool.fields.id'], width: 36 },
	{ id: 'swatch', label: m['filament.fields.colorHex'], width: 22 },
	{ id: 'name', label: m['filament.fields.name'], width: 100 },
	{ id: 'material', label: m['filament.fields.material'], width: 72 },
	{ id: 'vendor', label: m['filament.fields.vendor'], width: 110 },
	{ id: 'diameter', label: m['filament.fields.diameter'], width: 70, align: 'right' },
	{ id: 'progress', label: ng.spool_columns_progress, width: 56 },
	{ id: 'remaining', label: m['spool.fields.remainingWeight'], width: 60, align: 'right' },
	{ id: 'used', label: m['spool.fields.usedWeight'], width: 76, align: 'right' },
	{ id: 'price', label: m['spool.fields.price'], width: 76, align: 'right' },
	{ id: 'lot', label: m['spool.fields.lotNr'], width: 84 },
	{ id: 'location', label: m['spool.fields.location'], width: 96 },
	{ id: 'firstUsed', label: m['spool.fields.firstUsed'], width: 84 },
	{ id: 'lastUsed', label: m['spool.fields.lastUsed'], width: 84 },
	{ id: 'registered', label: m['spool.fields.registered'], width: 84 },
	{ id: 'comment', label: m['spool.fields.comment'], width: 140 }
];

export const EXTRA_PREFIX = 'extra.';

export function columnCatalogue(spoolFields: readonly FieldDef[]): ColumnDef[] {
	return [
		...BUILT_IN,
		...spoolFields.map((f) => ({ id: `${EXTRA_PREFIX}${f.key}`, label: () => f.name, width: 100 }))
	];
}
