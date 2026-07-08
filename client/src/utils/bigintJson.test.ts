import { describe, expect, it } from "vitest";
import { parseJsonWithBigIntIds } from "./bigintJson";

// Issue #69: CockroachDB ids exceed Number.MAX_SAFE_INTEGER and were rounded by JSON.parse,
// making the client request the wrong id and 404.
describe("parseJsonWithBigIntIds", () => {
  it("keeps an oversized integer id as an exact string instead of rounding it", () => {
    const parsed = parseJsonWithBigIntIds('{"id":1134663890672549889}') as { id: string };
    expect(parsed.id).toBe("1134663890672549889");
  });

  it("leaves safely-representable ids and numbers as numbers", () => {
    const parsed = parseJsonWithBigIntIds('{"id":42,"price":12.5}') as { id: number; price: number };
    expect(parsed.id).toBe(42);
    expect(typeof parsed.id).toBe("number");
    expect(parsed.price).toBe(12.5);
  });

  it("handles arrays and nested objects", () => {
    const parsed = parseJsonWithBigIntIds('[{"id":1134663890672549889},{"id":7}]') as { id: number | string }[];
    expect(parsed[0].id).toBe("1134663890672549889");
    expect(parsed[1].id).toBe(7);
  });
});
