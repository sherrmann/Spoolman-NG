import { describe, expect, it } from "vitest";
import { StringifiedExtras, StringifiedExtrasForUpdate } from "./extraFields";

// The API merges `extra` per key on spools, filaments and vendors, so an edit form has to send
// null to clear a field: a key left out keeps whatever it held (upstream issue 1141).
describe("StringifiedExtrasForUpdate", () => {
  it("JSON-encodes values that are set", () => {
    const out = StringifiedExtrasForUpdate({ id: 1, extra: { slot: "A3", count: 4, tags: ["x"] } });
    expect(out.extra).toEqual({ slot: '"A3"', count: "4", tags: '["x"]' });
  });

  it("sends a field left empty as null so the API clears it", () => {
    const out = StringifiedExtrasForUpdate({ id: 1, extra: { slot: undefined, bought: null } });
    expect(out.extra).toEqual({ slot: null, bought: null });
  });

  it("keeps falsy values that are real values", () => {
    const out = StringifiedExtrasForUpdate({ id: 1, extra: { count: 0, flag: false, note: "" } });
    expect(out.extra).toEqual({ count: "0", flag: "false", note: '""' });
  });

  it("leaves extra unset when the form has none", () => {
    expect(
      StringifiedExtrasForUpdate<{ id: number; extra?: Record<string, unknown> }>({ id: 1 }).extra,
    ).toBeUndefined();
  });
});

describe("StringifiedExtras", () => {
  it("still drops an empty field on create, where absent and empty mean the same", () => {
    const out = StringifiedExtras({ id: 1, extra: { slot: undefined, count: 4 } });
    expect(JSON.parse(JSON.stringify(out.extra))).toEqual({ count: "4" });
  });
});
