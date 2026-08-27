/**
 * Pure PATCH /order/{id} body builders for the order edit view.
 *
 * Framework-free, like orderBody.ts, so the shape can be unit-tested against hand-computed
 * oracles without mounting a component.
 *
 * The backend (spoolman/api/v1/order.py `update`) replaces the *entire* line set whenever `lines`
 * is present in the PATCH body (`replace_lines = "lines" in patch_data`) — there is no per-line
 * patch. So every line must be sent back on every save, including already-arrived ones (with their
 * `arrived_at` preserved, or they'd revert to outstanding); only the edited un-arrived lines'
 * quantity/price get changed.
 *
 * This is also *why* the edit path differs from orderBody.ts's create path on blank optional
 * fields: buildNewOrderBody OMITS a blank order_number/url/comment (a brand-new order simply never
 * had one). buildOrderPatchBody instead sends an explicit `null` for a cleared field, because this
 * is an edit of an order that may already have a value set — omitting the key would leave the old
 * value in place rather than clearing it. Don't "simplify" these two into one convention; they
 * answer different questions ("what should exist" vs. "what should this become").
 */
// The wire shapes live in ./types beside the other contracts, so there is one definition of
// what the server is sent rather than one per builder.
import type { OrderLine, OrderPatchBody, OrderPatchLine } from './types';

/** One edited order line, in this client's domain shape: filament ids are strings here (see orderBody.ts). */
export interface OrderEditLineInput {
	filamentId: string;
	quantity: number;
	pricePerUnit?: number;
	arrivedAt?: string;
}

export interface LineEdit {
	quantity: number;
	pricePerUnit?: number;
}

/**
 * Convert a domain edited line to the wire shape. Guarded the same way orderBody.ts's toWireLine
 * is: a bare `Number(...)` on an id that doesn't round-trip exactly would silently attach the line
 * to the wrong filament (CockroachDB ids exceed the range JS numbers represent exactly) rather
 * than fail loudly, so this throws instead.
 */
function toWirePatchLine(line: OrderEditLineInput): OrderPatchLine {
	const id = Number(line.filamentId);
	if (!Number.isSafeInteger(id) || String(id) !== line.filamentId.trim()) {
		throw new Error(`Filament id ${line.filamentId} cannot be sent as an integer without losing precision.`);
	}
	const wire: OrderPatchLine = { filament_id: id, quantity: line.quantity };
	if (line.pricePerUnit !== undefined) wire.price_per_unit = line.pricePerUnit;
	if (line.arrivedAt !== undefined) wire.arrived_at = line.arrivedAt;
	return wire;
}

/**
 * Rebuilds the full line array to send on a save: already-arrived lines pass through untouched
 * (including `arrivedAt`), un-arrived lines pick up their edit (keyed by line id) when one exists,
 * otherwise keep their current values.
 */
export function buildEditedLines(
	originalLines: OrderLine[],
	edits: Record<number, LineEdit>
): OrderEditLineInput[] {
	return originalLines.map((line) => {
		if (line.arrivedAt) {
			return {
				filamentId: line.filamentId,
				quantity: line.quantity,
				pricePerUnit: line.pricePerUnit,
				arrivedAt: line.arrivedAt
			};
		}
		const edit = edits[line.id];
		return {
			filamentId: line.filamentId,
			quantity: edit ? edit.quantity : line.quantity,
			pricePerUnit: edit ? edit.pricePerUnit : line.pricePerUnit
		};
	});
}

/** Trims a header text field to its sent value, or `null` when it's blank (clears the field). */
function trimmedOrNull(value: string): string | null {
	const trimmed = value.trim();
	return trimmed ? trimmed : null;
}

/**
 * PATCH /order/{id} body for the edit view's header + lines. Header text fields are always sent
 * (blank clears them via an explicit `null`) rather than omitted, since this is an edit of an
 * existing order, not a create — see the module doc comment above for why that's not the same
 * convention as orderBody.ts.
 */
export function buildOrderPatchBody(
	header: {
		shopId: number | null;
		orderedAt: string;
		orderNumber: string;
		url: string;
		comment: string;
	},
	lines: OrderEditLineInput[]
): OrderPatchBody {
	return {
		shop_id: header.shopId,
		ordered_at: header.orderedAt,
		order_number: trimmedOrNull(header.orderNumber),
		url: trimmedOrNull(header.url),
		comment: trimmedOrNull(header.comment),
		lines: lines.map(toWirePatchLine)
	};
}
