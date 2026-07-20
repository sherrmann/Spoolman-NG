import { IOrder } from "./model";

export interface LinesSummary {
  total: number;
  arrived: number;
  outstanding: number;
  filaments: number;
}

/** Roll an order's lines into counts for the Orders-list summary column (#298). */
export function summarizeLines(order: IOrder): LinesSummary {
  let total = 0;
  let arrived = 0;
  // Distinct filaments, not line count — a split line (same filament, e.g. partial arrival across
  // two lines) must not double-count.
  const filamentIds = new Set<number>();
  for (const l of order.lines) {
    total += l.quantity;
    if (l.arrived_at) arrived += l.quantity;
    filamentIds.add(l.filament_id);
  }
  return { total, arrived, outstanding: total - arrived, filaments: filamentIds.size };
}
