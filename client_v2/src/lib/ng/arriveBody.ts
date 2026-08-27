import type { ArriveBody } from './types';

/**
 * Pure POST /order/{id}/arrive body builder for the arrive dialog.
 *
 * Ported out of the React client's arriveModal.tsx (where `buildArriveBody` lived alongside the
 * component) into its own module -- same reason ordersState.ts and orderEditBody.ts are separate
 * files: it needs to be unit-tested against hand-computed bodies without mounting a component.
 *
 * Order-line ids are plain numbers in this client (unlike filament/vendor ids -- see
 * orderBody.ts), so there's no domain/wire id split to guard here.
 */

// One order line as the dialog sees it: the user's editable delivered `quantity` (defaulting to
// `outstanding`, the full remaining count on the line) and whether it's checked at all.
export interface ArriveLineInput {
	lineId: number;
	quantity: number;
	outstanding: number;
	selected: boolean;
}

/**
 * A delivered quantity below a line's outstanding count splits it (quantity included); a full
 * delivery omits `quantity` so the whole line simply gets an `arrived_at`. Unselected or
 * zero-quantity lines are dropped entirely -- omitting `lines` on the wire means "arrive
 * everything", which isn't what an unchecked row means.
 */
export function buildArriveBody(
	lines: ArriveLineInput[],
	createSpools: boolean,
	locationId?: number
): ArriveBody {
	const out = lines
		.filter((l) => l.selected && l.quantity > 0)
		.map((l) =>
			l.quantity >= l.outstanding ? { line_id: l.lineId } : { line_id: l.lineId, quantity: l.quantity }
		);
	const body: ArriveBody = { lines: out, create_spools: createSpools };
	if (locationId !== undefined) body.location_id = locationId;
	return body;
}
