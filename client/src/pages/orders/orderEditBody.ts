// Pure PATCH /order/{id} body builders for the order details/edit modal (gate-feedback item #5).
// Kept framework-free, like orderBody.ts, so the shape can be unit-tested against hand-computed
// oracles without touching antd/refine.
//
// The backend (spoolman/api/v1/order.py `update`) replaces the *entire* line set whenever `lines`
// is present in the PATCH body (`replace_lines = "lines" in patch_data`) — there is no per-line
// patch. So every line must be sent back on every save, including already-arrived ones (with their
// `arrived_at` preserved, or they'd revert to outstanding); only the edited un-arrived lines'
// quantity/price_per_unit actually change.

export interface OrderEditLineInput {
  filament_id: number;
  quantity: number;
  price_per_unit?: number;
  arrived_at?: string;
}

export interface OrderPatchBody {
  shop_id: number | null;
  ordered_at: string;
  order_number: string | null;
  url: string | null;
  comment: string | null;
  lines: OrderEditLineInput[];
}

export interface OriginalOrderLine {
  id: number;
  filament_id: number;
  quantity: number;
  price_per_unit?: number;
  arrived_at?: string;
}

export interface LineEdit {
  quantity: number;
  price_per_unit?: number;
}

/**
 * Rebuilds the full line array to send on a save: already-arrived lines pass through untouched
 * (including `arrived_at`), un-arrived lines pick up their edit (keyed by line id) when one
 * exists, otherwise keep their current values.
 */
export function buildEditedLines(
  originalLines: OriginalOrderLine[],
  edits: Record<number, LineEdit>,
): OrderEditLineInput[] {
  return originalLines.map((line) => {
    if (line.arrived_at) {
      return {
        filament_id: line.filament_id,
        quantity: line.quantity,
        price_per_unit: line.price_per_unit,
        arrived_at: line.arrived_at,
      };
    }
    const edit = edits[line.id];
    return {
      filament_id: line.filament_id,
      quantity: edit ? edit.quantity : line.quantity,
      price_per_unit: edit ? edit.price_per_unit : line.price_per_unit,
    };
  });
}

/** Trims a header text field to its sent value, or `null` when it's blank (clears the field). */
function trimmedOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

/**
 * PATCH /order/{id} body for the details/edit modal's header + lines. Header text fields are
 * always sent (blank clears them via an explicit `null`) rather than omitted, since this is an
 * edit of an existing order, not a create — an omitted field would leave the old value in place.
 */
export function buildOrderPatchBody(
  header: {
    shopId: number | null;
    orderedAt: string;
    orderNumber: string;
    url: string;
    comment: string;
  },
  lines: OrderEditLineInput[],
): OrderPatchBody {
  return {
    shop_id: header.shopId,
    ordered_at: header.orderedAt,
    order_number: trimmedOrNull(header.orderNumber),
    url: trimmedOrNull(header.url),
    comment: trimmedOrNull(header.comment),
    lines: lines.map((l) => ({ ...l })),
  };
}
