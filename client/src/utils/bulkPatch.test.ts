import { afterEach, describe, expect, it, vi } from "vitest";
import { bulkPatch } from "./bulkPatch";

// The shared bulk helper (#73) loops the existing single-resource PATCH — no bulk backend endpoint —
// so these tests pin the resource-scoped URL, one PATCH per id, and partial-failure counting.

vi.mock("./url", () => ({ getAPIURL: () => "http://test/api/v1" }));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("bulkPatch", () => {
  it("PATCHes /{resource}/{id} for each id with the shared body", async () => {
    const seen: { url: string; method?: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        seen.push({ url, method: init.method, body: JSON.parse(init.body as string) });
        return { ok: true } as Response;
      }),
    );

    const failed = await bulkPatch("filament", [4, 5], { price: 25 });

    expect(failed).toBe(0);
    expect(seen.map((c) => c.url)).toEqual(["http://test/api/v1/filament/4", "http://test/api/v1/filament/5"]);
    expect(seen.every((c) => c.method === "PATCH")).toBe(true);
    expect(seen.every((c) => JSON.stringify(c.body) === JSON.stringify({ price: 25 }))).toBe(true);
  });

  it("counts failures instead of throwing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => ({ ok: !url.endsWith("/spool/2") }) as Response),
    );

    const failed = await bulkPatch("spool", [1, 2, 3], { archived: true });

    expect(failed).toBe(1);
  });
});
