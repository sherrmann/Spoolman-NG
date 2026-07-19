import { describe, it, expect } from "vitest";
import { openOrdersByFilament } from "./openOrders";
import { IOrder } from "../orders/model";

const order = (o: Partial<IOrder>): IOrder => ({
  id: 1,
  registered: "",
  ordered_at: "2026-07-10T00:00:00Z",
  lines: [],
  state: "open",
  ...o,
});

describe("openOrdersByFilament", () => {
  it("maps a filament to its open order id and shop name", () => {
    const m = openOrdersByFilament([
      order({
        id: 5,
        shop: { id: 1, registered: "", name: "3DJake" },
        lines: [{ id: 1, filament_id: 10, quantity: 1 }],
      }),
    ]);
    expect(m.get(10)).toEqual({ order_id: 5, shop_name: "3DJake" });
  });
  it("prefers the oldest open order for a filament", () => {
    const m = openOrdersByFilament([
      order({ id: 5, ordered_at: "2026-07-15T00:00:00Z", lines: [{ id: 1, filament_id: 10, quantity: 1 }] }),
      order({ id: 6, ordered_at: "2026-07-01T00:00:00Z", lines: [{ id: 2, filament_id: 10, quantity: 1 }] }),
    ]);
    expect(m.get(10)?.order_id).toBe(6);
  });
  it("ignores arrived lines and arrived orders", () => {
    const m = openOrdersByFilament([
      order({
        id: 5,
        state: "arrived",
        lines: [{ id: 1, filament_id: 10, quantity: 1, arrived_at: "2026-07-11T00:00:00Z" }],
      }),
    ]);
    expect(m.has(10)).toBe(false);
  });
});
