import { describe, expect, it } from "vitest";
import { EntityType, Field, FieldType, sortFieldsByOrder } from "./queryFields";

// #65: custom fields must render in their configured `order`, not stored/insertion order. useGetFields
// sorts once so every consumer (forms, list columns, show page) is consistent — these tests pin that
// comparator.

function field(key: string, order: number): Field {
  return { key, name: key, order, field_type: FieldType.text, entity_type: EntityType.filament };
}

describe("sortFieldsByOrder", () => {
  it("orders fields by their numeric order regardless of input order", () => {
    const sorted = sortFieldsByOrder([field("c", 2), field("a", 0), field("b", 1)]);
    expect(sorted.map((f) => f.key)).toEqual(["a", "b", "c"]);
  });

  it("is a stable sort for equal orders and does not mutate the input", () => {
    const input = [field("x", 5), field("y", 5), field("z", 1)];
    const sorted = sortFieldsByOrder(input);
    expect(sorted.map((f) => f.key)).toEqual(["z", "x", "y"]);
    // Original array is untouched.
    expect(input.map((f) => f.key)).toEqual(["x", "y", "z"]);
  });
});
