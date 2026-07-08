import { describe, expect, it } from "vitest";
import { columnIdOf, computeEffectiveOrder, moveInOrder, orderColumns } from "./columnOrder";

describe("columnIdOf", () => {
  it("reads a string dataIndex verbatim and joins an array path", () => {
    expect(columnIdOf({ dataIndex: "id" })).toBe("id");
    expect(columnIdOf({ dataIndex: "filament.combined_name" })).toBe("filament.combined_name");
    expect(columnIdOf({ dataIndex: ["extra", "spool_color"] })).toBe("extra.spool_color");
    expect(columnIdOf({})).toBeUndefined();
  });
});

describe("computeEffectiveOrder (#94)", () => {
  const natural = ["id", "vendor", "name", "material"];

  it("returns the natural order when nothing is saved", () => {
    expect(computeEffectiveOrder(undefined, natural)).toEqual(natural);
  });

  it("applies the saved order and drops ids no longer present", () => {
    expect(computeEffectiveOrder(["material", "id", "gone"], natural)).toEqual(["material", "id", "vendor", "name"]);
  });

  it("appends columns the saved order doesn't mention (e.g. new extra fields) at the end", () => {
    // saved order predates the "material" column being added.
    expect(computeEffectiveOrder(["name", "id", "vendor"], natural)).toEqual(["name", "id", "vendor", "material"]);
  });
});

describe("orderColumns (#94)", () => {
  it("sorts built columns by the given order, pinning id-less columns (actions) last", () => {
    const cols = [
      { dataIndex: "id" },
      { dataIndex: "vendor" },
      { dataIndex: "material" },
      { title: "actions" }, // no dataIndex
    ];
    const ordered = orderColumns(cols, ["material", "vendor", "id"]);
    expect(ordered.map((c) => columnIdOf(c) ?? "actions")).toEqual(["material", "vendor", "id", "actions"]);
  });

  it("keeps columns absent from the order in their relative position at the end", () => {
    const cols = [{ dataIndex: "a" }, { dataIndex: "b" }, { dataIndex: "c" }];
    // Only "c" is ordered; a and b keep their relative order after it.
    expect(orderColumns(cols, ["c"]).map((c) => c.dataIndex)).toEqual(["c", "a", "b"]);
  });
});

describe("moveInOrder", () => {
  it("moves an item forward and backward without mutating the input", () => {
    const order = ["a", "b", "c", "d"];
    expect(moveInOrder(order, 0, 2)).toEqual(["b", "c", "a", "d"]);
    expect(moveInOrder(order, 3, 1)).toEqual(["a", "d", "b", "c"]);
    expect(order).toEqual(["a", "b", "c", "d"]);
  });
});
