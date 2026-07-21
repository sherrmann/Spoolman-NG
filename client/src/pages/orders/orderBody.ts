// Pure POST /order body builders for the US1 "Mark as ordered" dialog and the US2 bulk
// create-order modal (#298). Kept framework-free so the shape can be unit-tested against
// hand-computed oracles without touching antd/refine.

export interface OrderLineInput {
  filament_id: number;
  quantity: number;
  price_per_unit?: number;
}

export interface NewOrderBody {
  shop_id?: number;
  order_number?: string;
  url?: string;
  comment?: string;
  ordered_at: string;
  lines: OrderLineInput[];
}

/** POST /order body for the US1 single-line "Mark as ordered" dialog. */
export function buildMarkOrderedBody(input: {
  filament_id: number;
  quantity: number;
  orderedAt: string;
  shopId?: number;
  pricePerUnit?: number;
  orderNumber?: string;
  url?: string;
}): NewOrderBody {
  const line: OrderLineInput = { filament_id: input.filament_id, quantity: input.quantity };
  if (input.pricePerUnit !== undefined) line.price_per_unit = input.pricePerUnit;
  const body: NewOrderBody = { ordered_at: input.orderedAt, lines: [line] };
  if (input.shopId !== undefined) body.shop_id = input.shopId;
  if (input.orderNumber) body.order_number = input.orderNumber;
  if (input.url) body.url = input.url;
  return body;
}

/** POST /order body for the US2 bulk order: one line per selected filament. */
export function buildBulkOrderBody(selected: OrderLineInput[], orderedAt: string, shopId?: number): NewOrderBody {
  const body: NewOrderBody = { ordered_at: orderedAt, lines: selected.map((s) => ({ ...s })) };
  if (shopId !== undefined) body.shop_id = shopId;
  return body;
}

/**
 * POST /order body for the from-scratch "New order" builder (#324): the full header (shop, date,
 * order number, url, comment) plus one line per picked filament. Unlike the details/edit PATCH
 * builder (orderEditBody.ts), this is a *create* — blank optional fields are omitted rather than
 * sent as explicit `null`, matching buildMarkOrderedBody's convention.
 */
export function buildNewOrderBody(input: {
  orderedAt: string;
  lines: OrderLineInput[];
  shopId?: number;
  orderNumber?: string;
  url?: string;
  comment?: string;
}): NewOrderBody {
  const body: NewOrderBody = { ordered_at: input.orderedAt, lines: input.lines.map((l) => ({ ...l })) };
  if (input.shopId !== undefined) body.shop_id = input.shopId;
  if (input.orderNumber) body.order_number = input.orderNumber;
  if (input.url) body.url = input.url;
  if (input.comment) body.comment = input.comment;
  return body;
}
