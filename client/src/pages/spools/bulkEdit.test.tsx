import { afterEach, describe, expect, it, vi } from "vitest";
import { bulkPatchSpools } from "./bulkEdit";

// #73 bulk edit applies changes by looping the existing single-spool PATCH — no bulk backend
// endpoint — so these tests pin that contract: one PATCH per id with the shared body, and partial
// failures are counted (not thrown) so one bad row doesn't abort the rest of the batch.

vi.mock("../../utils/url", () => ({ getAPIURL: () => "http://test/api/v1" }));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("bulkPatchSpools", () => {
  it("PATCHes every id with the same body and reports zero failures", async () => {
    const seen: { url: string; method?: string; body: unknown }[] = [];
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      seen.push({ url, method: init.method, body: JSON.parse(init.body as string) });
      return { ok: true } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    const failed = await bulkPatchSpools([1, 2, 3], { location: "Shelf A" });

    expect(failed).toBe(0);
    expect(seen).toHaveLength(3);
    expect(seen.map((c) => c.url)).toEqual([
      "http://test/api/v1/spool/1",
      "http://test/api/v1/spool/2",
      "http://test/api/v1/spool/3",
    ]);
    expect(seen.every((c) => c.method === "PATCH")).toBe(true);
    expect(seen.every((c) => JSON.stringify(c.body) === JSON.stringify({ location: "Shelf A" }))).toBe(true);
  });

  it("counts failed rows instead of throwing, so the batch is not aborted", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      // The second spool fails; the others still get their PATCH.
      return { ok: !url.endsWith("/spool/2") } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    const failed = await bulkPatchSpools([1, 2, 3], { archived: true });

    expect(failed).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
