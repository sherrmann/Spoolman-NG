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
  for (const l of order.lines) {
    total += l.quantity;
    if (l.arrived_at) arrived += l.quantity;
  }
  return { total, arrived, outstanding: total - arrived, filaments: order.lines.length };
}
