import { describe, expect, it } from "vitest";
import {
  CLEAR_PAYLOAD,
  buildScanPayload,
  isClearScan,
  looksLikeRetailBarcode,
  parseScanResult,
  type ScanResource,
} from "./scan";

// The star test (TESTING_STRATEGY.md §2): the QR print dialogs (encoder) and the
// scanner modal (decoder) are independent code paths that must agree. A
// build → parse round-trip is therefore a genuine oracle — not a re-statement of
// either implementation. Regression coverage for the filament-scan formats and the
// base-path-tolerant URL regex added in PR #4.

const RESOURCES: ScanResource[] = ["spool", "filament", "location"];
const LETTER: Record<ScanResource, string> = { spool: "S", filament: "F", location: "L" };

describe("buildScanPayload ↔ parseScanResult round-trip", () => {
  it.each(RESOURCES)("round-trips the custom scheme for a %s", (resource) => {
    const payload = buildScanPayload(resource, 42);
    expect(payload).toBe(`WEB+SPOOLMAN:${LETTER[resource]}-42`);
    const parsed = parseScanResult(payload);
    expect(parsed).toEqual({ resource, id: "42", path: `/${resource}/show/42` });
  });

  it.each(RESOURCES)("round-trips a plain-origin deep-link URL for a %s", (resource) => {
    const payload = buildScanPayload(resource, 7, "https://spools.example.com");
    expect(payload).toBe(`https://spools.example.com/${resource}/show/7`);
    expect(parseScanResult(payload)).toEqual({ resource, id: "7", path: `/${resource}/show/7` });
  });

  it.each(RESOURCES)("round-trips a sub-path (base-path) deploy URL for a %s", (resource) => {
    // The base-path case is exactly what the widened URL regex added support for.
    const payload = buildScanPayload(resource, 9, "https://host.example.com/spoolman");
    expect(payload).toBe(`https://host.example.com/spoolman/${resource}/show/9`);
    expect(parseScanResult(payload)).toEqual({ resource, id: "9", path: `/${resource}/show/9` });
  });
});

describe("parseScanResult", () => {
  it("is case-insensitive on the custom scheme", () => {
    expect(parseScanResult("web+spoolman:f-3")).toEqual({ resource: "filament", id: "3", path: "/filament/show/3" });
    expect(parseScanResult("WEB+SPOOLMAN:S-3")).toEqual({ resource: "spool", id: "3", path: "/spool/show/3" });
  });

  it.each(RESOURCES)("rejects characters before the custom scheme for a %s (leading anchor)", (resource) => {
    const prefix = LETTER[resource];
    // The ^ anchor must reject anything preceding "web+spoolman:".
    expect(parseScanResult(`x web+spoolman:${prefix}-1`)).toBeNull();
    expect(parseScanResult(`javascript:web+spoolman:${prefix}-1`)).toBeNull();
  });

  it("keeps spool, filament and location targets distinct", () => {
    expect(parseScanResult("web+spoolman:s-1")?.resource).toBe("spool");
    expect(parseScanResult("web+spoolman:f-1")?.resource).toBe("filament");
    expect(parseScanResult("web+spoolman:l-1")?.resource).toBe("location");
    expect(parseScanResult("https://h/spool/show/1")?.resource).toBe("spool");
    expect(parseScanResult("https://h/filament/show/1")?.resource).toBe("filament");
    expect(parseScanResult("https://h/location/show/1")?.resource).toBe("location");
  });

  it.each([
    ["an unknown scheme", "web+spoolman:x-1"],
    ["a non-numeric id", "web+spoolman:f-abc"],
    ["trailing junk", "web+spoolman:f-12 and more"],
    ["an empty string", ""],
    ["an unrelated url", "https://example.com/"],
    ["a wrong path", "https://example.com/spool/edit/1"],
    ["a bare number", "12"],
  ])("rejects %s", (_label, raw) => {
    expect(parseScanResult(raw)).toBeNull();
  });

  it("requires the id to be the whole trailing segment (anchored)", () => {
    // No partial match: extra path after the id must not sneak through.
    expect(parseScanResult("https://h/spool/show/1/extra")).toBeNull();
  });

  it.each(RESOURCES)("accepts an http:// (non-https) deep-link URL for a %s", (resource) => {
    // Covers the optional 's' in https? — both schemes must resolve.
    expect(parseScanResult(`http://host/${resource}/show/5`)).toEqual({
      resource,
      id: "5",
      path: `/${resource}/show/5`,
    });
  });

  it.each(RESOURCES)("parses a multi-digit id from a URL for a %s", (resource) => {
    // Covers [0-9]+ — the id is one-or-more digits, not exactly one.
    expect(parseScanResult(`https://host/${resource}/show/12345`)?.id).toBe("12345");
  });

  it.each(RESOURCES)("rejects characters before the scheme for a %s (leading anchor)", (resource) => {
    // The ^ anchor must reject anything preceding the URL.
    expect(parseScanResult(`x https://host/${resource}/show/1`)).toBeNull();
    expect(parseScanResult(`data:text/html,https://host/${resource}/show/1`)).toBeNull();
  });

  it.each(RESOURCES)("rejects trailing characters after the id for a %s (trailing anchor)", (resource) => {
    // The $ anchor must reject anything following the id.
    expect(parseScanResult(`https://host/${resource}/show/1x`)).toBeNull();
    expect(parseScanResult(`https://host/${resource}/show/1/extra`)).toBeNull();
  });
});

describe("isClearScan (#132)", () => {
  it("recognises the reserved clear sentinel, case-insensitively and trimmed", () => {
    expect(isClearScan(CLEAR_PAYLOAD)).toBe(true);
    expect(isClearScan("web+spoolman:clear")).toBe(true);
    expect(isClearScan("  WEB+SPOOLMAN:CLEAR  ")).toBe(true);
  });

  it("does not treat a spool/filament code or junk as clear", () => {
    expect(isClearScan("web+spoolman:s-1")).toBe(false);
    expect(isClearScan("clear")).toBe(false);
    expect(isClearScan("")).toBe(false);
  });

  it("is not mistaken for a navigation target", () => {
    expect(parseScanResult(CLEAR_PAYLOAD)).toBeNull();
  });
});

describe("looksLikeRetailBarcode (#97b)", () => {
  it.each(["12345678", "012345678905", "4006381333931", "00012345678905"])("accepts %s", (code) => {
    expect(looksLikeRetailBarcode(code)).toBe(true);
  });

  it.each([
    ["too short", "1234567"],
    ["odd length (9)", "123456789"],
    ["non-numeric", "400638133393X"],
    ["a spoolman code", "web+spoolman:s-1"],
    ["empty", ""],
  ])("rejects %s", (_label, code) => {
    expect(looksLikeRetailBarcode(code)).toBe(false);
  });
});
