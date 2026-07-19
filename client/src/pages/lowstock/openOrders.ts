import { IOrder } from "../orders/model";

/**
 * Map each on-order filament to the OLDEST open order that contains it (#298), for the Low Stock
 * "Ordered · <age> · <shop>" pill and its order link. Mirrors the server's `on_order = oldest open`
 * rule so the pill and the filament's on_order field agree.
 */
export function openOrdersByFilament(orders: IOrder[]): Map<number, { order_id: number; shop_name?: string }> {
  const oldest = new Map<number, { order_id: number; ordered_at: string; shop_name?: string }>();
  for (const order of orders) {
    if (order.state !== "open") continue;
    for (const line of order.lines) {
      if (line.arrived_at) continue;
      const prev = oldest.get(line.filament_id);
      if (!prev || new Date(order.ordered_at).getTime() < new Date(prev.ordered_at).getTime()) {
        oldest.set(line.filament_id, { order_id: order.id, ordered_at: order.ordered_at, shop_name: order.shop?.name });
      }
    }
  }
  const out = new Map<number, { order_id: number; shop_name?: string }>();
  for (const [fid, v] of oldest) out.set(fid, { order_id: v.order_id, shop_name: v.shop_name });
  return out;
}
