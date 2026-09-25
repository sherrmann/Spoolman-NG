/**
 * Turn the bulk-edit form into the patch applied to every selected spool (#412).
 *
 * Tick-to-change, as in the classic client: an unticked field is left out of the patch and so
 * left alone on every spool, and a ticked field that is empty clears it. That is the only way to
 * say "clear the location on these twelve spools", and the reason the tick exists at all: an
 * empty box alone cannot tell "clear it" from "leave it".
 */
import type { SpoolPatch } from '$lib/types';

export const BULK_FIELDS = ['location', 'lot', 'price', 'comment'] as const;
export type BulkField = (typeof BULK_FIELDS)[number];

export interface BulkEditForm {
	ticked: Record<BulkField, boolean>;
	values: Record<BulkField, string>;
}

export type BulkEditBody = { patch: SpoolPatch } | { error: 'nothing' | 'price' };

export function bulkEditBody({ ticked, values }: BulkEditForm): BulkEditBody {
	if (!BULK_FIELDS.some((f) => ticked[f])) return { error: 'nothing' };
	const patch: SpoolPatch = {};
	if (ticked.location) patch.location = values.location.trim();
	if (ticked.lot) patch.lot = values.lot.trim();
	if (ticked.comment) patch.comment = values.comment;
	if (ticked.price) {
		const raw = values.price.trim();
		if (raw === '') {
			// Clears the spool's own price, so it falls back to the filament's again.
			patch.price = undefined;
		} else {
			const price = Number(raw.replace(',', '.'));
			if (!Number.isFinite(price) || price < 0) return { error: 'price' };
			patch.price = price;
		}
	}
	return { patch };
}
