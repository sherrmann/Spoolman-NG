import { describe, expect, it } from "vitest";
import { isDuplicateVendorName, normalizeVendorName } from "./functions";

// The soft duplicate-name warning on the vendor create form (#82) is driven by these pure helpers.
describe("normalizeVendorName (#82)", () => {
  it("trims, lowercases, and collapses inner whitespace", () => {
    expect(normalizeVendorName("  Acme  ")).toBe("acme");
    expect(normalizeVendorName("ACME")).toBe("acme");
    expect(normalizeVendorName("Ac  me")).toBe("ac me");
    expect(normalizeVendorName("Ac me")).toBe("ac me");
  });
});

describe("isDuplicateVendorName (#82)", () => {
  const existing = ["Prusament", "Polymaker", "Bambu Lab"];

  it("matches case/whitespace-insensitively", () => {
    expect(isDuplicateVendorName("prusament", existing)).toBe(true);
    expect(isDuplicateVendorName("  PRUSAMENT ", existing)).toBe(true);
    expect(isDuplicateVendorName("bambu  lab", existing)).toBe(true);
  });

  it("does not match a genuinely new name", () => {
    expect(isDuplicateVendorName("Sunlu", existing)).toBe(false);
    expect(isDuplicateVendorName("Prusamentt", existing)).toBe(false);
  });

  it("treats empty / whitespace-only names as non-duplicates (required rule owns that)", () => {
    expect(isDuplicateVendorName("", existing)).toBe(false);
    expect(isDuplicateVendorName("   ", existing)).toBe(false);
  });
});
