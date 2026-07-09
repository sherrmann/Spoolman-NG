import { describe, expect, it } from "vitest";
import { ISpool } from "../pages/spools/model";
import { buildSpoolActionUrl } from "./spoolActionLinks";

function spool(over: Partial<ISpool> = {}): ISpool {
  return {
    id: 42,
    registered: "2024-01-01T00:00:00Z",
    filament: { id: 7, registered: "2024-01-01", density: 1.24, diameter: 1.75, extra: {} },
    used_weight: 0,
    used_length: 0,
    archived: false,
    extra: {},
    ...over,
  };
}

describe("buildSpoolActionUrl (#140)", () => {
  it("substitutes the spool id", () => {
    expect(buildSpoolActionUrl("http://mmu/set?spool={id}", spool())).toBe("http://mmu/set?spool=42");
  });

  it("substitutes multiple tokens including the filament id", () => {
    expect(buildSpoolActionUrl("http://x/{id}/{filament_id}", spool())).toBe("http://x/42/7");
  });

  it("URL-encodes substituted values", () => {
    expect(buildSpoolActionUrl("http://x?loc={location}", spool({ location: "Dry Box A" }))).toBe(
      "http://x?loc=Dry%20Box%20A",
    );
  });

  it("resolves an unset field to an empty string", () => {
    expect(buildSpoolActionUrl("http://x?lot={lot_nr}", spool({ lot_nr: undefined }))).toBe("http://x?lot=");
  });

  it("resolves an unknown token to an empty string", () => {
    expect(buildSpoolActionUrl("http://x?q={nope}", spool())).toBe("http://x?q=");
  });
});
