/**
 * Pure POST /order body builders for the mark-as-ordered dialog and the bulk create-order modal.
 *
 * Framework-free on purpose, so the shape can be checked against hand-computed bodies without
 * standing up a component -- the same reason the React original is a separate module.
 */
import type { NewOrderBody } from './types';

/** One order line, in this client's domain shape: filament ids are strings here. */
export interface OrderLineInput {
	filamentId: string;
	quantity: number;
	pricePerUnit?: number;
}

/**
 * Convert a domain line to the wire shape, where `filament_id` is an integer.
 *
 * The conversion is guarded rather than a bare `Number(...)`. This client keeps entity ids as
 * strings because CockroachDB ids exceed the range JS represents exactly, and an id that loses
 * precision here would not fail -- it would silently attach the order line to a *different*
 * filament, or to none. That is data corruption a user would find weeks later while looking at
 * an order they never placed, so it throws instead.
 */
function toWireLine(line: OrderLineInput): NewOrderBody['lines'][number] {
	const id = Number(line.filamentId);
	if (!Number.isSafeInteger(id) || String(id) !== line.filamentId.trim()) {
		throw new Error(
			`Filament id ${line.filamentId} cannot be sent as an integer without losing precision.`,
		);
	}
	const wire: NewOrderBody['lines'][number] = { filament_id: id, quantity: line.quantity };
	if (line.pricePerUnit !== undefined) wire.price_per_unit = line.pricePerUnit;
	return wire;
}

/** Body for the single-line "mark as ordered" dialog. */
export function buildMarkOrderedBody(input: {
	filamentId: string;
	quantity: number;
	orderedAt: string;
	shopId?: number;
	pricePerUnit?: number;
	orderNumber?: string;
	url?: string;
}): NewOrderBody {
	const body: NewOrderBody = {
		ordered_at: input.orderedAt,
		lines: [
			toWireLine({
				filamentId: input.filamentId,
				quantity: input.quantity,
				pricePerUnit: input.pricePerUnit,
			}),
		],
	};
	if (input.shopId !== undefined) body.shop_id = input.shopId;
	// Falsy rather than undefined: an empty string from a cleared input means "not given", and
	// sending it would store a blank order number that reads as a real one in the orders list.
	if (input.orderNumber) body.order_number = input.orderNumber;
	if (input.url) body.url = input.url;
	return body;
}

/** Body for the bulk order: one line per selected filament. */
export function buildBulkOrderBody(
	selected: OrderLineInput[],
	orderedAt: string,
	shopId?: number,
): NewOrderBody {
	const body: NewOrderBody = { ordered_at: orderedAt, lines: selected.map(toWireLine) };
	if (shopId !== undefined) body.shop_id = shopId;
	return body;
}

/** Body for the from-scratch order builder: full header plus one line per picked filament. */
export function buildNewOrderBody(input: {
	orderedAt: string;
	lines: OrderLineInput[];
	shopId?: number;
	orderNumber?: string;
	url?: string;
	comment?: string;
}): NewOrderBody {
	const body: NewOrderBody = { ordered_at: input.orderedAt, lines: input.lines.map(toWireLine) };
	if (input.shopId !== undefined) body.shop_id = input.shopId;
	if (input.orderNumber) body.order_number = input.orderNumber;
	if (input.url) body.url = input.url;
	if (input.comment) body.comment = input.comment;
	return body;
}
