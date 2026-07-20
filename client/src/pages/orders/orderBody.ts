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
