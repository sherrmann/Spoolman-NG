import { describe, it, expect } from "vitest";
import { summarizeLines } from "./ordersState";
import { IOrder } from "./model";

const order = (o: Partial<IOrder>): IOrder => ({
  id: 1,
  registered: "",
  ordered_at: "2026-07-10T00:00:00Z",
  lines: [],
  state: "open",
  ...o,
});

describe("summarizeLines", () => {
  it("rolls quantities into total/arrived/outstanding + filament count", () => {
    const s = summarizeLines(
      order({
        lines: [
          { id: 1, filament_id: 1, quantity: 4, arrived_at: "2026-07-11T00:00:00Z" },
          { id: 2, filament_id: 2, quantity: 3 },
        ],
      }),
    );
    expect(s).toEqual({ total: 7, arrived: 4, outstanding: 3, filaments: 2 });
  });
  it("reports zero for a note-only order", () => {
    expect(summarizeLines(order({ lines: [] }))).toEqual({ total: 0, arrived: 0, outstanding: 0, filaments: 0 });
  });
});
