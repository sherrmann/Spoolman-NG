import dayjs from "dayjs";
import { describe, expect, it } from "vitest";
import { IFilament } from "../filaments/model";
import { ISpool } from "../spools/model";
import { IVendor } from "../vendors/model";
import {
  computeLowStock,
  DEFAULT_TOTAL_WEIGHT,
  distinctMaterialCount,
  getColorHex,
  getFilamentName,
  getSpoolName,
  getWeightPct,
  lowStockNotOnOrderCount,
  staleSpools,
  locationBreakdown,
  materialBreakdown,
  recentSpools,
  registeredWithinDays,
  spoolStockWeight,
  topVendor,
  totalRemainingWeight,
  totalValue,
  vendorBreakdown,
} from "./analytics";

// Fixtures

function vendor(name: string): IVendor {
  return { id: 1, registered: "2024-01-01", name, extra: {} };
}

function filament(over: Partial<IFilament> = {}): IFilament {
  return { id: 1, registered: "2024-01-01", density: 1.24, diameter: 1.75, extra: {}, ...over };
}

let nextId = 1;
function spool(over: Partial<ISpool> = {}): ISpool {
  const { filament: fil, ...rest } = over;
  return {
    id: nextId++,
    registered: "2024-01-01T00:00:00Z",
    filament: fil ?? filament(),
    used_weight: 0,
    used_length: 0,
    archived: false,
    extra: {},
    ...rest,
  };
}

// spoolStockWeight: the fallback chain that already caused a bug

describe("spoolStockWeight", () => {
  it("prefers remaining over initial over filament weight", () => {
    expect(spoolStockWeight(spool({ remaining_weight: 1, initial_weight: 2, filament: filament({ weight: 3 }) }))).toBe(
      1,
    );
    expect(spoolStockWeight(spool({ initial_weight: 2, filament: filament({ weight: 3 }) }))).toBe(2);
    expect(spoolStockWeight(spool({ filament: filament({ weight: 3 }) }))).toBe(3);
  });

  it("is 0 when no weight information exists", () => {
    expect(spoolStockWeight(spool({ filament: filament() }))).toBe(0);
  });
});

describe("totalRemainingWeight", () => {
  it("is 0 for an empty inventory", () => {
    expect(totalRemainingWeight([])).toBe(0);
  });

  it("sums the effective stock weight across mixed fallback cases", () => {
    const spools = [
      spool({ remaining_weight: 500 }),
      spool({ initial_weight: 800 }),
      spool({ filament: filament({ weight: 1000 }) }),
      spool({ filament: filament() }), // contributes 0
    ];
    expect(totalRemainingWeight(spools)).toBe(500 + 800 + 1000 + 0);
  });
});

describe("totalValue", () => {
  it("scales each spool's price by its remaining fraction (hand-computed)", () => {
    // 10 € spool, half used → worth 5 €.
    expect(totalValue([spool({ price: 10, initial_weight: 1000, remaining_weight: 500 })])).toBe(5);
    // 20 € spool, three quarters used → worth 5 €.
    expect(totalValue([spool({ price: 20, initial_weight: 1000, remaining_weight: 250 })])).toBe(5);
  });

  it("falls back to the filament price when the spool has none (spool price wins otherwise)", () => {
    // No spool price → the filament's 20 € applies: 20 × 250/1000 = 5 €.
    expect(
      totalValue([spool({ initial_weight: 1000, remaining_weight: 250, filament: filament({ price: 20 }) })]),
    ).toBe(5);
    // Both set → the spool's own 10 € wins over the filament's 99 €: 10 × 500/1000 = 5 €.
    expect(
      totalValue([
        spool({ price: 10, initial_weight: 1000, remaining_weight: 500, filament: filament({ price: 99 }) }),
      ]),
    ).toBe(5);
  });

  it("uses filament.weight as the denominator when initial_weight is absent", () => {
    // 16 € spool of an 800 g filament with 200 g left → 16 × 200/800 = 4 €.
    expect(totalValue([spool({ price: 16, remaining_weight: 200, filament: filament({ weight: 800 }) })])).toBe(4);
  });

  it("counts a spool with no weight information as full", () => {
    expect(totalValue([spool({ price: 12 })])).toBe(12);
  });

  it("clamps the remaining fraction to 0..1", () => {
    // Over-full (bad data) still counts at most the full price…
    expect(totalValue([spool({ price: 10, initial_weight: 1000, remaining_weight: 2000 })])).toBe(10);
    // …and over-used never goes negative.
    expect(totalValue([spool({ price: 10, initial_weight: 1000, remaining_weight: -50 })])).toBe(0);
  });

  it("ignores spools without a price anywhere and sums the rest", () => {
    const spools = [
      spool({ price: 10, initial_weight: 1000, remaining_weight: 500 }), // 5
      spool({ initial_weight: 1000, remaining_weight: 1000 }), // no price → 0
      spool({ price: 5.5 }), // full → 5.5
    ];
    expect(totalValue(spools)).toBe(10.5);
  });

  it("is 0 for an empty inventory", () => {
    expect(totalValue([])).toBe(0);
  });

  it("never exceeds the inventory's full purchase value (invariant)", () => {
    const spools = [
      spool({ price: 10, initial_weight: 1000, remaining_weight: 700 }),
      spool({ price: 30, initial_weight: 1000, remaining_weight: 100 }),
      spool({ initial_weight: 500, remaining_weight: 400, filament: filament({ price: 25 }) }),
    ];
    const fullPurchase = 10 + 30 + 25;
    expect(totalValue(spools)).toBeLessThanOrEqual(fullPurchase);
    expect(totalValue(spools)).toBe(10 * 0.7 + 30 * 0.1 + 25 * 0.8);
  });
});

describe("distinctMaterialCount", () => {
  it("counts each material once, ignoring filaments without one", () => {
    const filaments = [
      filament({ material: "PLA" }),
      filament({ material: "PLA" }),
      filament({ material: "PETG" }),
      filament({}), // no material → not counted
      filament({ material: "" }), // empty string → not counted
    ];
    expect(distinctMaterialCount(filaments)).toBe(2);
  });

  it("is 0 for an empty catalog", () => {
    expect(distinctMaterialCount([])).toBe(0);
  });
});

describe("computeLowStock", () => {
  const F = 200; // fallback grams

  it("flags a filament at or below its explicit threshold, not one strictly above", () => {
    const below = filament({ id: 1, low_stock_threshold: 500, remaining_weight: 400 });
    const at = filament({ id: 2, low_stock_threshold: 500, remaining_weight: 500 });
    const above = filament({ id: 3, low_stock_threshold: 500, remaining_weight: 600 });
    const { explicit, count } = computeLowStock([below, at, above], F);
    expect(explicit.map((r) => r.filament.id)).toEqual([1, 2]);
    expect(count).toBe(2);
  });

  it("uses the gram fallback for filaments without an explicit threshold", () => {
    const caught = filament({ id: 1, remaining_weight: 150 }); // <= 200 fallback
    const fine = filament({ id: 2, remaining_weight: 250 }); // > 200 fallback
    const { explicit, fallback } = computeLowStock([caught, fine], F);
    expect(explicit).toEqual([]);
    expect(fallback.map((r) => r.filament.id)).toEqual([1]);
    expect(fallback[0].reason).toBe("fallback");
  });

  it("disables the fallback when fallbackG <= 0 (only explicit thresholds flag)", () => {
    const noThreshold = filament({ id: 1, remaining_weight: 10 });
    const explicitLow = filament({ id: 2, low_stock_threshold: 100, remaining_weight: 50 });
    const { explicit, fallback } = computeLowStock([noThreshold, explicitLow], 0);
    expect(fallback).toEqual([]);
    expect(explicit.map((r) => r.filament.id)).toEqual([2]);
  });

  it("never flags a filament whose aggregate remaining weight is not populated", () => {
    expect(computeLowStock([filament({ low_stock_threshold: 500 })], F).count).toBe(0);
  });

  it("orders each section by largest shortfall first", () => {
    const small = filament({ id: 1, low_stock_threshold: 500, remaining_weight: 450 }); // short 50
    const large = filament({ id: 2, low_stock_threshold: 1000, remaining_weight: 100 }); // short 900
    const mid = filament({ id: 3, low_stock_threshold: 800, remaining_weight: 500 }); // short 300
    expect(computeLowStock([small, large, mid], F).explicit.map((r) => r.filament.id)).toEqual([2, 3, 1]);
  });

  it("sinks on-order filaments to the bottom of their section", () => {
    const plain = filament({ id: 1, low_stock_threshold: 500, remaining_weight: 400 }); // short 100, not ordered
    const ordered = filament({
      id: 2,
      low_stock_threshold: 1000,
      remaining_weight: 100, // short 900, but on order -> sinks below the smaller shortfall
      on_order: { order_id: 7, ordered_at: "2026-07-10T00:00:00Z" },
    });
    expect(computeLowStock([ordered, plain], F).explicit.map((r) => r.filament.id)).toEqual([1, 2]);
  });
});

// The always-visible Low Stock nav item's red badge (#298 gate tweak) counts flagged filaments
// that are NOT already on order — an on-order row is being handled, so it shouldn't nag.
describe("lowStockNotOnOrderCount", () => {
  const F = 200;

  it("counts flagged rows across both sections, excluding on-order ones", () => {
    const plain = filament({ id: 1, low_stock_threshold: 500, remaining_weight: 400 });
    const ordered = filament({
      id: 2,
      remaining_weight: 150, // caught by the fallback
      on_order: { order_id: 7, ordered_at: "2026-07-10T00:00:00Z" },
    });
    const plainFallback = filament({ id: 3, remaining_weight: 100 });
    const sections = computeLowStock([plain, ordered, plainFallback], F);
    expect(lowStockNotOnOrderCount(sections)).toBe(2);
  });

  it("is zero when nothing is flagged, or everything flagged is already on order", () => {
    expect(lowStockNotOnOrderCount(computeLowStock([], F))).toBe(0);
    const allOrdered = filament({
      id: 1,
      low_stock_threshold: 500,
      remaining_weight: 400,
      on_order: { order_id: 1, ordered_at: "2026-07-10T00:00:00Z" },
    });
    expect(lowStockNotOnOrderCount(computeLowStock([allOrdered], F))).toBe(0);
  });
});

describe("getFilamentName", () => {
  it("prefixes the vendor name when present", () => {
    expect(getFilamentName(filament({ name: "Galaxy Black", vendor: vendor("Prusa") }))).toBe("Prusa - Galaxy Black");
  });

  it("falls back to the name, then the id, without a vendor", () => {
    expect(getFilamentName(filament({ name: "Generic PLA" }))).toBe("Generic PLA");
    expect(getFilamentName(filament({ id: 7, name: undefined }))).toBe("7");
  });
});

describe("recentSpools", () => {
  it("returns most-recently-used first and excludes never-used spools", () => {
    const old = spool({ last_used: "2024-01-01T00:00:00Z" });
    const mid = spool({ last_used: "2024-03-01T00:00:00Z" });
    const recent = spool({ last_used: "2024-06-01T00:00:00Z" });
    const never = spool({});
    const result = recentSpools([old, never, recent, mid]);
    expect(result).toEqual([recent, mid, old]);
  });

  it("caps the list at the given limit (default 5)", () => {
    const many = Array.from({ length: 7 }, (_, i) => spool({ last_used: `2024-06-0${i + 1}T00:00:00Z` }));
    expect(recentSpools(many)).toHaveLength(5);
    expect(recentSpools(many, 2)).toHaveLength(2);
  });

  it("does not mutate the input array", () => {
    const input = [spool({ last_used: "2024-01-01T00:00:00Z" }), spool({ last_used: "2024-06-01T00:00:00Z" })];
    const snapshot = [...input];
    recentSpools(input);
    expect(input).toEqual(snapshot);
  });
});

describe("materialBreakdown", () => {
  it("groups by material, counts and sums weight, heaviest first", () => {
    const spools = [
      spool({ remaining_weight: 300, filament: filament({ material: "PLA" }) }),
      spool({ remaining_weight: 200, filament: filament({ material: "PLA" }) }),
      spool({ remaining_weight: 900, filament: filament({ material: "PETG" }) }),
    ];
    expect(materialBreakdown(spools)).toEqual([
      ["PETG", { count: 1, weight: 900 }],
      ["PLA", { count: 2, weight: 500 }],
    ]);
  });

  it("buckets spools without a material under 'Unknown'", () => {
    const result = materialBreakdown([spool({ remaining_weight: 100, filament: filament() })]);
    expect(result).toEqual([["Unknown", { count: 1, weight: 100 }]]);
  });

  it("preserves the invariants: counts sum to spool count, weights sum to total", () => {
    const spools = [
      spool({ remaining_weight: 300, filament: filament({ material: "PLA" }) }),
      spool({ initial_weight: 200, filament: filament({ material: "ABS" }) }),
      spool({ filament: filament({ material: "PLA", weight: 400 }) }),
    ];
    const breakdown = materialBreakdown(spools);
    const countSum = breakdown.reduce((n, [, s]) => n + s.count, 0);
    const weightSum = breakdown.reduce((w, [, s]) => w + s.weight, 0);
    expect(countSum).toBe(spools.length);
    expect(weightSum).toBe(totalRemainingWeight(spools));
  });
});

describe("locationBreakdown", () => {
  it("groups by location, most-populated first, with a fallback bucket for empty", () => {
    // Distinct counts (3/2/1) so the descending sort order is actually exercised.
    const spools = [
      spool({ location: "Shelf A" }),
      spool({ location: "Shelf A" }),
      spool({ location: "Shelf A" }),
      spool({ location: "Shelf B" }),
      spool({ location: "" }),
      spool({}),
    ];
    expect(locationBreakdown(spools, "No location")).toEqual([
      ["Shelf A", 3],
      ["No location", 2],
      ["Shelf B", 1],
    ]);
  });

  it("counts sum to the spool count (invariant)", () => {
    const spools = [spool({ location: "A" }), spool({ location: "B" }), spool({ location: "A" })];
    const total = locationBreakdown(spools, "None").reduce((n, [, c]) => n + c, 0);
    expect(total).toBe(spools.length);
  });
});

describe("vendorBreakdown / topVendor", () => {
  it("groups by vendor name (missing -> '?'), most-populated first", () => {
    // Distinct counts (3/2/1) AND an input order that is the reverse of the sorted
    // order, so simply dropping the sort (or a no-op comparator) is caught.
    const spools = [
      spool({ filament: filament({ vendor: vendor("Globex") }) }),
      spool({ filament: filament() }),
      spool({ filament: filament() }),
      spool({ filament: filament({ vendor: vendor("Acme") }) }),
      spool({ filament: filament({ vendor: vendor("Acme") }) }),
      spool({ filament: filament({ vendor: vendor("Acme") }) }),
    ];
    expect(vendorBreakdown(spools)).toEqual([
      ["Acme", 3],
      ["?", 2],
      ["Globex", 1],
    ]);
  });

  it("topVendor picks the busiest vendor, and is '-' for an empty inventory", () => {
    const spools = [
      spool({ filament: filament({ vendor: vendor("Acme") }) }),
      spool({ filament: filament({ vendor: vendor("Globex") }) }),
      spool({ filament: filament({ vendor: vendor("Acme") }) }),
    ];
    expect(topVendor(spools)).toBe("Acme");
    expect(topVendor([])).toBe("-");
  });
});

describe("registeredWithinDays", () => {
  const now = dayjs("2024-06-15T12:00:00Z");

  it("counts spools registered inside the window and excludes older ones", () => {
    const spools = [
      spool({ registered: "2024-06-10T12:00:00Z" }), // 5 days ago → in
      spool({ registered: "2024-01-01T12:00:00Z" }), // months ago → out
    ];
    expect(registeredWithinDays(spools, 30, now)).toBe(1);
  });

  it("treats the exact cutoff as outside the window (strict isAfter)", () => {
    const exactly30 = spool({ registered: now.subtract(30, "day").toISOString() });
    expect(registeredWithinDays([exactly30], 30, now)).toBe(0);
  });

  it("defaults 'now' to the current time when omitted", () => {
    // Exercises the default-parameter branch; empty input keeps it clock-independent.
    expect(registeredWithinDays([], 30)).toBe(0);
    // A spool registered in the far past is never within a 30-day window of "now".
    expect(registeredWithinDays([spool({ registered: "2000-01-01T00:00:00Z" })], 30)).toBe(0);
  });
});

describe("presentation helpers", () => {
  it("getColorHex normalises to a single leading '#' and defaults to grey", () => {
    expect(getColorHex(spool({ filament: filament({ color_hex: "ff8800" }) }))).toBe("#ff8800");
    expect(getColorHex(spool({ filament: filament({ color_hex: "#ff8800" }) }))).toBe("#ff8800");
    expect(getColorHex(spool({ filament: filament() }))).toBe("#555555");
  });

  it("getSpoolName combines vendor and name, falling back to name then id", () => {
    expect(getSpoolName(spool({ filament: filament({ vendor: vendor("Acme"), name: "Red" }) }))).toBe("Acme - Red");
    expect(getSpoolName(spool({ filament: filament({ name: "Red" }) }))).toBe("Red");
    expect(getSpoolName(spool({ filament: filament({ id: 77 }) }))).toBe("77");
  });

  it("getWeightPct clamps to 0–100 and applies the weight fallback", () => {
    expect(getWeightPct(spool({ initial_weight: 1000, remaining_weight: 500 }))).toBe(50);
    // initial_weight takes precedence over filament.weight for the total: 500/1000 = 50%,
    // not 500/500 = 100%. Locks the precedence order of the ?? fallback chain.
    expect(
      getWeightPct(spool({ initial_weight: 1000, remaining_weight: 500, filament: filament({ weight: 500 }) })),
    ).toBe(50);
    expect(getWeightPct(spool({ initial_weight: 1000, remaining_weight: 2000 }))).toBe(100); // clamped
    expect(getWeightPct(spool({ initial_weight: 1000, remaining_weight: 0 }))).toBe(0);
    // No weights → total defaults to DEFAULT_TOTAL_WEIGHT and remaining defaults to total → 100%.
    expect(getWeightPct(spool({ filament: filament() }))).toBe(100);
    expect(DEFAULT_TOTAL_WEIGHT).toBe(1000);
  });
});

// #202: the "Gathering Dust" card lists the least-recently-used active spools. Never-used
// spools rank by their registration date (their only age signal); near-empty spools are
// excluded — a finished spool is "stale" forever but the right action is archiving it.
describe("staleSpools (#202)", () => {
  const base = { filament: filament({ weight: 1000 }) };

  it("orders by last_used ascending, interleaving never-used spools by registered date", () => {
    const oldNeverUsed = spool({ ...base, registered: "2023-01-01T00:00:00Z" });
    const usedLongAgo = spool({ ...base, last_used: "2024-06-01T00:00:00Z", registered: "2024-01-01T00:00:00Z" });
    const usedRecently = spool({ ...base, last_used: "2026-07-01T00:00:00Z", registered: "2024-01-01T00:00:00Z" });
    const result = staleSpools([usedRecently, oldNeverUsed, usedLongAgo]);
    expect(result.map((r) => r.spool.id)).toEqual([oldNeverUsed.id, usedLongAgo.id, usedRecently.id]);
  });

  it("flags never-used spools and dates them by registration", () => {
    const s = spool({ ...base, registered: "2023-01-01T00:00:00Z" });
    const [entry] = staleSpools([s]);
    expect(entry.neverUsed).toBe(true);
    expect(entry.staleSince).toBe("2023-01-01T00:00:00Z");
  });

  it("excludes near-empty spools", () => {
    const depleted = spool({ ...base, remaining_weight: 10, last_used: "2020-01-01T00:00:00Z" });
    const stale = spool({ ...base, remaining_weight: 500, last_used: "2024-01-01T00:00:00Z" });
    expect(staleSpools([depleted, stale]).map((r) => r.spool.id)).toEqual([stale.id]);
  });

  it("caps at the limit", () => {
    const spools = Array.from({ length: 8 }, (_, i) =>
      spool({ ...base, last_used: `2024-0${(i % 8) + 1}-01T00:00:00Z` }),
    );
    expect(staleSpools(spools).length).toBe(5);
    expect(staleSpools(spools, 3).length).toBe(3);
  });

  it("does not mutate its input", () => {
    const spools = [
      spool({ ...base, last_used: "2024-06-01T00:00:00Z" }),
      spool({ ...base, last_used: "2023-06-01T00:00:00Z" }),
    ];
    const ids = spools.map((s) => s.id);
    staleSpools(spools);
    expect(spools.map((s) => s.id)).toEqual(ids);
  });
});
