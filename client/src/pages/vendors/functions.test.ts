import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../utils/authReloadHandler";
import { getOrCreateVendorFromExternal, isDuplicateVendorName, normalizeVendorName } from "./functions";

vi.mock("../../utils/authReloadHandler", () => ({ apiFetch: vi.fn() }));

// The soft duplicate-name warning on the vendor create form (#82) is driven by these pure helpers.
describe("normalizeVendorName (#82)", () => {
  it("trims, lowercases, and collapses inner whitespace", () => {
    expect(normalizeVendorName("  Acme  ")).toBe("acme");
    expect(normalizeVendorName("ACME")).toBe("acme");
    expect(normalizeVendorName("Ac  me")).toBe("ac me");
    expect(normalizeVendorName("Ac me")).toBe("ac me");
  });
});

describe("isDuplicateVendorName (#82)", () => {
  const existing = ["Prusament", "Polymaker", "Bambu Lab"];

  it("matches case/whitespace-insensitively", () => {
    expect(isDuplicateVendorName("prusament", existing)).toBe(true);
    expect(isDuplicateVendorName("  PRUSAMENT ", existing)).toBe(true);
    expect(isDuplicateVendorName("bambu  lab", existing)).toBe(true);
  });

  it("does not match a genuinely new name", () => {
    expect(isDuplicateVendorName("Sunlu", existing)).toBe(false);
    expect(isDuplicateVendorName("Prusamentt", existing)).toBe(false);
  });

  it("treats empty / whitespace-only names as non-duplicates (required rule owns that)", () => {
    expect(isDuplicateVendorName("", existing)).toBe(false);
    expect(isDuplicateVendorName("   ", existing)).toBe(false);
  });
});

// Importing a SpoolmanDB filament must reuse a hand-made vendor of the same name rather than
// creating a duplicate (upstream Donkie/Spoolman#1181).
describe("getOrCreateVendorFromExternal", () => {
  type FakeVendor = { id: number; name: string; external_id?: string };
  const mockedFetch = vi.mocked(apiFetch);

  /** Serve GET /vendor like the server: the filters are substring matches unless quoted. */
  function serveVendors(vendors: FakeVendor[]) {
    mockedFetch.mockImplementation(async (input, init) => {
      if (init?.method === "POST") {
        return Response.json({ id: 99, ...JSON.parse(init.body as string) });
      }
      const params = new URL(String(input), "http://localhost").searchParams;
      const externalId = params.get("external_id");
      const name = params.get("name");
      const rows = vendors.filter((v) => {
        if (externalId !== null) {
          return v.external_id === externalId.replace(/^"|"$/g, "");
        }
        return name === null || v.name.toLowerCase().includes(name.toLowerCase());
      });
      return Response.json(rows);
    });
  }

  const posts = () => mockedFetch.mock.calls.filter(([, init]) => init?.method === "POST");

  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("prefers the vendor with a matching external_id over one with the same name", async () => {
    serveVendors([
      { id: 1, name: "Prusa" },
      { id: 2, name: "Renamed", external_id: "Prusa" },
    ]);
    expect((await getOrCreateVendorFromExternal("Prusa")).id).toBe(2);
    expect(posts()).toHaveLength(0);
  });

  it("reuses a same-name vendor without an external_id, ignoring case and spacing", async () => {
    serveVendors([
      { id: 1, name: "Prusament" },
      { id: 3, name: "  bambu   LAB " },
    ]);
    expect((await getOrCreateVendorFromExternal("Bambu Lab")).id).toBe(3);
    expect(posts()).toHaveLength(0);
  });

  it("does not reuse a vendor whose name only contains the manufacturer", async () => {
    serveVendors([{ id: 1, name: "Prusament" }]);
    const vendor = await getOrCreateVendorFromExternal("Prusa");
    expect(vendor.id).toBe(99);
    expect(posts()).toHaveLength(1);
  });

  it("creates the vendor when nothing matches", async () => {
    serveVendors([{ id: 1, name: "Polymaker" }]);
    const vendor = await getOrCreateVendorFromExternal("Prusa");
    expect(vendor).toMatchObject({ id: 99, name: "Prusa", external_id: "Prusa" });
    expect(posts()).toHaveLength(1);
  });
});
