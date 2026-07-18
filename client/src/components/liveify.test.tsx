// #226: websocket payloads omit the REST-only aggregate fields (spool_count, remaining_weight,
// filament_count — "null in nested/websocket payloads" per the API models), and useLiveify
// replaces the whole row with the transformed payload. Without handing the previous row to the
// transform, any live update blanks those columns until a manual reload. These tests pin (a) the
// carry-forward helper and (b) that useLiveify actually passes the previous row to the transform.
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

type Callback = (event: { payload: { data: { id: number } & Record<string, unknown> } }) => void;
const captured: { callback?: Callback } = {};

vi.mock("./liveProvider", () => ({
  default: () => ({
    subscribe: (opts: { callback: Callback }) => {
      captured.callback = opts.callback;
      return {};
    },
    unsubscribe: vi.fn(),
  }),
}));
vi.mock("../utils/url", () => ({ getAPIURL: () => "http://test/api/v1" }));

import { carryForwardFields, useLiveify } from "./liveify";

interface Row {
  id: number;
  name?: string;
  spool_count?: number;
  remaining_weight?: number;
}

describe("carryForwardFields (#226)", () => {
  it("backfills fields the payload omitted from the previous row", () => {
    const prev: Row = { id: 1, name: "old", spool_count: 3, remaining_weight: 750 };
    const payload: Row = { id: 1, name: "new" };
    expect(carryForwardFields(payload, prev, ["spool_count", "remaining_weight"])).toEqual({
      id: 1,
      name: "new",
      spool_count: 3,
      remaining_weight: 750,
    });
  });

  it("keeps payload values when present and works without a previous row", () => {
    const payload: Row = { id: 1, spool_count: 5 };
    expect(carryForwardFields(payload, { id: 1, spool_count: 3 }, ["spool_count"]).spool_count).toBe(5);
    expect(carryForwardFields(payload, undefined, ["spool_count"])).toEqual(payload);
  });
});

describe("useLiveify passes the previous row to the transform (#226)", () => {
  it("lets the transform preserve aggregate columns across a live update", () => {
    const initial: Row[] = [{ id: 1, name: "PLA", spool_count: 3, remaining_weight: 750 }];
    const transform = (payload: Row, previous?: Row) =>
      carryForwardFields(payload, previous, ["spool_count", "remaining_weight"]);

    const { result } = renderHook(() => useLiveify<Row>("filament", initial, transform));
    act(() => {
      captured.callback?.({ payload: { data: { id: 1, name: "PLA Matte" } } });
    });

    expect(result.current).toEqual([{ id: 1, name: "PLA Matte", spool_count: 3, remaining_weight: 750 }]);
  });
});
