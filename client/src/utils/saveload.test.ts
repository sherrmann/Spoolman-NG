import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useInitialTableState, useSavedState } from "./saveload";

// Oracle: the OBSERVABLE state of localStorage and the value the next mount reads
// — never which storage method was called. These are regression tests for the
// "undefined poisons localStorage" bug (PR #27); each one fails against the old
// code and passes against the fix.
describe("useSavedState", () => {
  const key = (id: string) => `savedStates-${id}`;

  it("returns the default when nothing is stored", () => {
    const { result } = renderHook(() => useSavedState("empty", "fallback"));
    expect(result.current[0]).toBe("fallback");
  });

  it("persists a value and restores it on a fresh mount", () => {
    const first = renderHook(() => useSavedState("roundtrip", "init"));
    act(() => first.result.current[1]("chosen"));
    expect(JSON.parse(localStorage.getItem(key("roundtrip"))!)).toBe("chosen");

    // A brand-new hook instance (simulates a page reload) reads it back.
    const second = renderHook(() => useSavedState("roundtrip", "init"));
    expect(second.result.current[0]).toBe("chosen");
  });

  it("removes the key instead of writing the string 'undefined' when set to undefined", () => {
    const { result } = renderHook(() => useSavedState<string | undefined>("clearable", "start"));
    act(() => result.current[1]("value"));
    expect(localStorage.getItem(key("clearable"))).toBe('"value"');

    act(() => result.current[1](undefined));
    // The bug wrote the literal string "undefined"; the fix removes the key.
    expect(localStorage.getItem(key("clearable"))).toBeNull();
    expect(localStorage.getItem(key("clearable"))).not.toBe("undefined");
  });

  it("heals a key already poisoned with the string 'undefined' and returns the default", () => {
    // Simulate storage left behind by an older build.
    localStorage.setItem(key("poisoned"), "undefined");

    const { result } = renderHook(() => useSavedState("poisoned", "healthy"));
    // Must fall back to the default rather than throw on JSON.parse("undefined").
    expect(result.current[0]).toBe("healthy");

    // ...and the poisoned value must not survive as-is.
    expect(localStorage.getItem(key("poisoned"))).not.toBe("undefined");
  });

  it("falls back to the default for any unparseable stored value", () => {
    localStorage.setItem(key("garbage"), "{not valid json");
    const { result } = renderHook(() => useSavedState("garbage", 42));
    expect(result.current[0]).toBe(42);
  });

  it.each([
    ["a string", "hi"],
    ["the number zero", 0],
    ["false", false],
    ["an empty string", ""],
    ["an object", { a: 1, b: [2, 3] }],
  ])("round-trips %s without dropping it", (_label, value) => {
    const first = renderHook(() => useSavedState<unknown>("valid", "def"));
    act(() => first.result.current[1](value));
    const second = renderHook(() => useSavedState<unknown>("valid", "def"));
    expect(second.result.current[0]).toEqual(value);
  });
});

// Oracle: the returned TableState and the observable persistence — a corrupt saved value
// (poisoned localStorage or a hand-edited/truncated shared URL hash) must fall back to the
// defaults and clear the bad source, never throw out of the hook (which would white-screen
// the list page). Issue #44.
describe("useInitialTableState corrupt-state healing", () => {
  const DEFAULT_SORTERS = [{ field: "id", order: "asc" }];

  beforeEach(() => {
    localStorage.clear();
    window.location.hash = "";
  });
  afterEach(() => {
    localStorage.clear();
    window.location.hash = "";
  });

  const setHash = (key: string, value: string) => {
    const p = new URLSearchParams();
    p.set(key, value);
    window.location.hash = p.toString();
  };

  it("returns the documented defaults when nothing is stored", () => {
    const { result } = renderHook(() => useInitialTableState("tbl"));
    expect(result.current.sorters).toEqual(DEFAULT_SORTERS);
    expect(result.current.filters).toEqual([]);
    expect(result.current.showColumns).toBeUndefined();
  });

  it("reads a valid stored value", () => {
    localStorage.setItem("tbl-sorters", JSON.stringify([{ field: "name", order: "desc" }]));
    const { result } = renderHook(() => useInitialTableState("tbl"));
    expect(result.current.sorters).toEqual([{ field: "name", order: "desc" }]);
  });

  it("falls back and clears a corrupt localStorage value instead of throwing", () => {
    localStorage.setItem("tbl-sorters", "{not valid json");
    let result: ReturnType<typeof useInitialTableState> | undefined;
    expect(() => {
      result = renderHook(() => useInitialTableState("tbl")).result.current;
    }).not.toThrow();
    expect(result!.sorters).toEqual(DEFAULT_SORTERS);
    // The poisoned key is cleared so it can't keep breaking the page.
    expect(localStorage.getItem("tbl-sorters")).toBeNull();
  });

  it("falls back and clears a corrupt URL-hash value (bad shared link)", () => {
    setHash("filters", "{not valid json");
    let result: ReturnType<typeof useInitialTableState> | undefined;
    expect(() => {
      result = renderHook(() => useInitialTableState("tbl")).result.current;
    }).not.toThrow();
    expect(result!.filters).toEqual([]);
    expect(new URLSearchParams(window.location.hash.substring(1)).has("filters")).toBe(false);
  });

  it("heals a corrupt showColumns value to undefined", () => {
    localStorage.setItem("tbl-showColumns", "not json");
    const { result } = renderHook(() => useInitialTableState("tbl"));
    expect(result.current.showColumns).toBeUndefined();
    expect(localStorage.getItem("tbl-showColumns")).toBeNull();
  });
});
