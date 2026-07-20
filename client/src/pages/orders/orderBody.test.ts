import { describe, it, expect } from "vitest";
import { buildMarkOrderedBody, buildBulkOrderBody } from "./orderBody";

describe("buildMarkOrderedBody", () => {
  it("builds a one-line order with shop, price, number, url and the (backdated) ordered_at", () => {
    expect(
      buildMarkOrderedBody({
        filament_id: 10,
        quantity: 2,
        orderedAt: "2026-07-01T00:00:00Z",
        shopId: 5,
        pricePerUnit: 19.9,
        orderNumber: "4711",
        url: "https://shop/4711",
      }),
    ).toEqual({
      shop_id: 5,
      order_number: "4711",
      url: "https://shop/4711",
      ordered_at: "2026-07-01T00:00:00Z",
      lines: [{ filament_id: 10, quantity: 2, price_per_unit: 19.9 }],
    });
  });
  it("omits shop/price/number/url when not given", () => {
    expect(buildMarkOrderedBody({ filament_id: 10, quantity: 1, orderedAt: "2026-07-19T00:00:00Z" })).toEqual({
      ordered_at: "2026-07-19T00:00:00Z",
      lines: [{ filament_id: 10, quantity: 1 }],
    });
  });
});

describe("buildBulkOrderBody", () => {
  it("maps selected filaments to one order with one line each", () => {
    expect(
      buildBulkOrderBody(
        [
          { filament_id: 10, quantity: 2 },
          { filament_id: 11, quantity: 1 },
        ],
        "2026-07-19T00:00:00Z",
        5,
      ),
    ).toEqual({
      shop_id: 5,
      ordered_at: "2026-07-19T00:00:00Z",
      lines: [
        { filament_id: 10, quantity: 2 },
        { filament_id: 11, quantity: 1 },
      ],
    });
  });
  it("omits shop_id when no shop chosen", () => {
    expect(buildBulkOrderBody([{ filament_id: 10, quantity: 1 }], "2026-07-19T00:00:00Z")).toEqual({
      ordered_at: "2026-07-19T00:00:00Z",
      lines: [{ filament_id: 10, quantity: 1 }],
    });
  });
});
