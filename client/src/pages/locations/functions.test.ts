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
