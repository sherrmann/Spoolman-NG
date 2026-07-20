import { describe, it, expect } from "vitest";
import { formatOrderedPill } from "./orderPill";

describe("formatOrderedPill", () => {
  const now = new Date("2026-07-19T00:00:00Z");
  it("shows age and shop", () => {
    expect(formatOrderedPill({ order_id: 1, ordered_at: "2026-07-16T00:00:00Z" }, "3DJake", now)).toBe(
      "Ordered · 3d · 3DJake",
    );
  });
  it("omits the shop when unknown", () => {
    expect(formatOrderedPill({ order_id: 1, ordered_at: "2026-07-18T00:00:00Z" }, undefined, now)).toBe("Ordered · 1d");
  });
  it("uses 'today' for a same-day order", () => {
    expect(formatOrderedPill({ order_id: 1, ordered_at: "2026-07-19T00:00:00Z" }, "Prusa", now)).toBe(
      "Ordered · today · Prusa",
    );
  });
});
