import { afterEach, describe, expect, it, vi } from "vitest";
import { getLocationByName, getOrCreateLocationByName } from "./functions";
import { ILocation } from "./model";

// The location-entity bridge helpers (#103) talk to /api/v1/locations via fetch. Mock fetch and
// assert the get-or-create + exact-name-match behaviour that backs the board's field editor.

function loc(over: Partial<ILocation>): ILocation {
  return { id: 1, registered: "2024-01-01", name: "X", extra: {}, ...over };
}

function mockFetch(handler: (url: string, init?: RequestInit) => { ok: boolean; body: unknown }) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const { ok, body } = handler(url, init);
    return { ok, json: async () => body } as Response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getLocationByName (#103)", () => {
  it("returns the exact-name match, not a partial one", async () => {
    mockFetch(() => ({ ok: true, body: [loc({ id: 7, name: "Dry Box 10" }), loc({ id: 8, name: "Dry Box 1" })] }));
    const result = await getLocationByName("Dry Box 1");
    expect(result?.id).toBe(8);
  });

  it("returns null when no row matches exactly", async () => {
    mockFetch(() => ({ ok: true, body: [loc({ id: 7, name: "Dry Box 10" })] }));
    expect(await getLocationByName("Dry Box 1")).toBeNull();
  });

  it("returns null on a non-ok response", async () => {
    mockFetch(() => ({ ok: false, body: null }));
    expect(await getLocationByName("Dry Box 1")).toBeNull();
  });
});

describe("getOrCreateLocationByName (#103)", () => {
  it("returns the existing row without POSTing", async () => {
    const fetchMock = mockFetch(() => ({ ok: true, body: [loc({ id: 5, name: "Shelf A" })] }));
    const result = await getOrCreateLocationByName("Shelf A");
    expect(result.id).toBe(5);
    expect(fetchMock).toHaveBeenCalledTimes(1); // only the lookup, no POST
  });

  it("POSTs a new row when none exists", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (init?.method === "POST") return { ok: true, body: loc({ id: 99, name: "New Box" }) };
      return { ok: true, body: [] }; // lookup finds nothing
    });
    const result = await getOrCreateLocationByName("New Box");
    expect(result.id).toBe(99);
    expect(fetchMock).toHaveBeenCalledTimes(2); // lookup + POST
    expect(fetchMock.mock.calls[1][1]?.method).toBe("POST");
  });
});

describe("API token attachment (#224)", () => {
  it("attaches the stored token as Authorization header on the create POST", async () => {
    localStorage.setItem("spoolmanApiToken", "sekrit-224");
    const fetchMock = mockFetch((url, init) => {
      if (init?.method === "POST") return { ok: true, body: loc({ id: 99, name: "New Box" }) };
      return { ok: true, body: [] };
    });

    await getOrCreateLocationByName("New Box");

    localStorage.removeItem("spoolmanApiToken");
    const headers = (fetchMock.mock.calls[1][1]?.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer sekrit-224");
  });
});

// #225: useRenameSpoolLocation carried Refine-v4 query keys (["default", "spool"]) while the app is
// on @refinedev/core v5, whose keys are prefixed with "data" (["data", "default", "spool", "list",
// ...]). React-query matches key prefixes from index 0, so both the optimistic update and the
// success invalidation matched nothing: the board kept showing the old location (and the settings
// sync effect then wrote the stale name back as a persisted ghost column).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { renameSpoolOrderKey, useRenameSpoolLocation } from "./functions";

const SPOOL_LIST_KEY = ["data", "default", "spool", "list", { filters: [], pagination: { mode: "off" } }];

describe("useRenameSpoolLocation (#225)", () => {
  it("optimistically renames matching spools in the v5 list cache and invalidates it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, text: async () => "", json: async () => ({}) }) as unknown as Response),
    );
    const queryClient = new QueryClient();
    queryClient.setQueryData(SPOOL_LIST_KEY, {
      data: [
        { id: 1, location: "Shelf A" },
        { id: 2, location: "Shelf B" },
      ],
      total: 2,
    });
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(QueryClientProvider, { client: queryClient }, children);

    const { result } = renderHook(() => useRenameSpoolLocation(), { wrapper });
    act(() => result.current.mutate({ old: "Shelf A", new: "Shelf C" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = queryClient.getQueryData<{ data: { id: number; location: string }[] }>(SPOOL_LIST_KEY);
    expect(cached?.data.map((s) => s.location)).toEqual(["Shelf C", "Shelf B"]);
    expect(queryClient.getQueryState(SPOOL_LIST_KEY)?.isInvalidated).toBe(true);
  });
});

describe("renameSpoolOrderKey (#225)", () => {
  it("moves the manual spool order from the old column name to the new one", () => {
    const orders = { "Shelf A": [3, 1, 2], "Shelf B": [9] };
    expect(renameSpoolOrderKey(orders, "Shelf A", "Shelf C")).toEqual({ "Shelf C": [3, 1, 2], "Shelf B": [9] });
  });

  it("is a no-op when the old name has no stored order", () => {
    const orders = { "Shelf B": [9] };
    expect(renameSpoolOrderKey(orders, "Shelf A", "Shelf C")).toEqual({ "Shelf B": [9] });
  });

  it("does not mutate its input", () => {
    const orders = { "Shelf A": [1] };
    renameSpoolOrderKey(orders, "Shelf A", "Shelf C");
    expect(orders).toEqual({ "Shelf A": [1] });
  });
});
