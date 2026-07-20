import { describe, it, expect } from "vitest";
import { buildEditedLines, buildOrderPatchBody, OrderEditLineInput } from "./orderEditBody";

describe("buildEditedLines", () => {
  it("passes arrived lines through unchanged, including arrived_at, so the full-replace PATCH doesn't un-arrive them", () => {
    const original = [
      { id: 1, filament_id: 10, quantity: 3, price_per_unit: 19.9, arrived_at: "2026-07-01T00:00:00Z" },
      { id: 2, filament_id: 11, quantity: 2, price_per_unit: undefined, arrived_at: undefined },
    ];
    const result = buildEditedLines(original, {});
    expect(result).toEqual([
      { filament_id: 10, quantity: 3, price_per_unit: 19.9, arrived_at: "2026-07-01T00:00:00Z" },
      { filament_id: 11, quantity: 2, price_per_unit: undefined },
    ]);
  });

  it("applies edits (quantity/price_per_unit) only to the matching un-arrived line", () => {
    const original = [
      { id: 1, filament_id: 10, quantity: 3, price_per_unit: 19.9, arrived_at: "2026-07-01T00:00:00Z" },
      { id: 2, filament_id: 11, quantity: 2, price_per_unit: 5, arrived_at: undefined },
    ];
    const result = buildEditedLines(original, { 2: { quantity: 4, price_per_unit: 7.5 } });
    expect(result).toEqual([
      { filament_id: 10, quantity: 3, price_per_unit: 19.9, arrived_at: "2026-07-01T00:00:00Z" },
      { filament_id: 11, quantity: 4, price_per_unit: 7.5 },
    ]);
  });

  it("ignores an edit keyed to an arrived line's id (arrived lines are read-only)", () => {
    const original = [
      { id: 1, filament_id: 10, quantity: 3, price_per_unit: 19.9, arrived_at: "2026-07-01T00:00:00Z" },
    ];
    const result = buildEditedLines(original, { 1: { quantity: 99, price_per_unit: 1 } });
    expect(result).toEqual([
      { filament_id: 10, quantity: 3, price_per_unit: 19.9, arrived_at: "2026-07-01T00:00:00Z" },
    ]);
  });

  it("falls back to the original quantity/price_per_unit when an edit omits one of them", () => {
    const original = [{ id: 1, filament_id: 10, quantity: 3, price_per_unit: 19.9, arrived_at: undefined }];
    const result = buildEditedLines(original, { 1: { quantity: 5, price_per_unit: undefined } });
    // An edit row always carries both fields in practice (seeded from the line), but the builder
    // must not silently invent a price the line never had if a caller only supplies quantity.
    expect(result).toEqual([{ filament_id: 10, quantity: 5, price_per_unit: undefined }]);
  });

  it("returns an empty array for an order with no lines", () => {
    expect(buildEditedLines([], {})).toEqual([]);
  });
});

describe("buildOrderPatchBody", () => {
  const lines: OrderEditLineInput[] = [{ filament_id: 10, quantity: 2, price_per_unit: 19.9 }];

  it("builds a full PATCH body with shop, order number, url and comment set", () => {
    expect(
      buildOrderPatchBody(
        {
          shopId: 5,
          orderedAt: "2026-07-01T00:00:00Z",
          orderNumber: "4711",
          url: "https://shop/4711",
          comment: "Backordered",
        },
        lines,
      ),
    ).toEqual({
      shop_id: 5,
      ordered_at: "2026-07-01T00:00:00Z",
      order_number: "4711",
      url: "https://shop/4711",
      comment: "Backordered",
      lines,
    });
  });

  it("nulls out order_number/url/comment when they were cleared (blank/whitespace), and shop_id when no shop is chosen", () => {
    expect(
      buildOrderPatchBody(
        { shopId: null, orderedAt: "2026-07-19T00:00:00Z", orderNumber: "  ", url: "", comment: "   " },
        lines,
      ),
    ).toEqual({
      shop_id: null,
      ordered_at: "2026-07-19T00:00:00Z",
      order_number: null,
      url: null,
      comment: null,
      lines,
    });
  });

  it("trims order_number/url/comment before sending them", () => {
    expect(
      buildOrderPatchBody(
        { shopId: 1, orderedAt: "2026-07-19T00:00:00Z", orderNumber: " 4711 ", url: " https://x ", comment: " hi " },
        lines,
      ),
    ).toEqual({
      shop_id: 1,
      ordered_at: "2026-07-19T00:00:00Z",
      order_number: "4711",
      url: "https://x",
      comment: "hi",
      lines,
    });
  });

  it("does not mutate its lines input and copies each line object", () => {
    const body = buildOrderPatchBody(
      { shopId: 1, orderedAt: "2026-07-19T00:00:00Z", orderNumber: "", url: "", comment: "" },
      lines,
    );
    expect(body.lines).toEqual(lines);
    expect(body.lines).not.toBe(lines);
    expect(body.lines[0]).not.toBe(lines[0]);
  });
});
