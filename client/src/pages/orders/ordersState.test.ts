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
  it("counts distinct filament_ids, not lines — a split line must not double-count", () => {
    const s = summarizeLines(
      order({
        lines: [
          { id: 1, filament_id: 5, quantity: 2 },
          { id: 2, filament_id: 5, quantity: 3, arrived_at: "2026-07-11T00:00:00Z" },
        ],
      }),
    );
    expect(s.filaments).toBe(1);
  });
  it("open order with outstanding lines reports a positive outstanding count for the state pill", () => {
    const s = summarizeLines(
      order({
        state: "open",
        lines: [
          { id: 1, filament_id: 1, quantity: 2 },
          { id: 2, filament_id: 2, quantity: 1, arrived_at: "2026-07-11T00:00:00Z" },
        ],
      }),
    );
    expect(s.outstanding).toBe(2);
  });
  it("fully arrived order reports zero outstanding for the state pill", () => {
    const s = summarizeLines(
      order({
        state: "arrived",
        lines: [{ id: 1, filament_id: 1, quantity: 3, arrived_at: "2026-07-11T00:00:00Z" }],
      }),
    );
    expect(s.outstanding).toBe(0);
  });
});
