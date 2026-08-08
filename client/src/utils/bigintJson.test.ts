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

  // #377: a long-looking float is not an oversized integer. json-bigint's own `storeAsString` gates
  // on raw literal length (>15 chars), not on integer-ness, so `0.30000000000000004` — ordinary
  // float64 noise from summing weights — used to come out as a *string*. That silently turned `+`
  // into concatenation everywhere the value was summed (home page totals), corrupting the result
  // long before `.toFixed()` crashed on it.
  it("parses a long noisy float as a number, not a string", () => {
    const parsed = parseJsonWithBigIntIds('{"used_weight":0.30000000000000004}') as {
      used_weight: number;
    };
    expect(typeof parsed.used_weight).toBe("number");
    expect(parsed.used_weight).toBeCloseTo(0.30000000000000004, 15);
  });

  it("still keeps a much larger oversized integer id as an exact string (#69)", () => {
    const parsed = parseJsonWithBigIntIds('{"id":123456789012345678901}') as { id: string };
    expect(parsed.id).toBe("123456789012345678901");
    expect(typeof parsed.id).toBe("string");
  });

  it("keeps an integer exactly at MAX_SAFE_INTEGER as a number, not a string", () => {
    // 9007199254740991 is 16 characters — past json-bigint's 15-char threshold — but it is exactly
    // representable, so it must come out as a number rather than needlessly becoming a string.
    const parsed = parseJsonWithBigIntIds('{"id":9007199254740991}') as { id: number };
    expect(parsed.id).toBe(Number.MAX_SAFE_INTEGER);
    expect(typeof parsed.id).toBe("number");
  });
});
