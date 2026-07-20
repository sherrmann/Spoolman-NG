import { describe, it, expect } from "vitest";
import { buildArriveBody } from "./arriveModal";

describe("buildArriveBody", () => {
  it("splits a partial line, keeps a full line as-is, and drops unselected lines", () => {
    const body = buildArriveBody(
      [
        { line_id: 1, quantity: 2, outstanding: 4, selected: true }, // partial -> split
        { line_id: 2, quantity: 1, outstanding: 1, selected: true }, // full -> no quantity
        { line_id: 3, quantity: 3, outstanding: 3, selected: false }, // unchecked -> omitted
      ],
      true,
      7,
    );
    expect(body).toEqual({
      lines: [{ line_id: 1, quantity: 2 }, { line_id: 2 }],
      create_spools: true,
      location_id: 7,
    });
  });
  it("omits location_id when no location chosen and drops zero-quantity lines", () => {
    const body = buildArriveBody([{ line_id: 1, quantity: 0, outstanding: 2, selected: true }], false);
    expect(body).toEqual({ lines: [], create_spools: false });
  });
});
