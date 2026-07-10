import { describe, expect, it } from "vitest";

import { decideScanAction, parseNdefCandidate } from "./scanActions";

describe("decideScanAction", () => {
  it("navigates for the custom scheme, for all three resources", () => {
    expect(decideScanAction("WEB+SPOOLMAN:S-42")).toEqual({
      kind: "navigate",
      target: { resource: "spool", id: "42", path: "/spool/show/42" },
    });
    expect(decideScanAction("web+spoolman:f-7")).toEqual({
      kind: "navigate",
      target: { resource: "filament", id: "7", path: "/filament/show/7" },
    });
    expect(decideScanAction("WEB+SPOOLMAN:L-3")).toEqual({
      kind: "navigate",
      target: { resource: "location", id: "3", path: "/location/show/3" },
    });
  });

  it("navigates for deep-link URLs from any host, tolerating base paths", () => {
    expect(decideScanAction("http://pi:7912/spool/show/12")).toMatchObject({
      kind: "navigate",
      target: { path: "/spool/show/12" },
    });
    expect(decideScanAction("https://nas.example.com/spoolman/spool/show/12")).toMatchObject({
      kind: "navigate",
      target: { path: "/spool/show/12" },
    });
  });

  it("recognises the clear sentinel and retail barcodes, and trims input", () => {
    expect(decideScanAction(" web+spoolman:clear ")).toEqual({ kind: "clear" });
    expect(decideScanAction("4009900484220")).toEqual({
      kind: "retail",
      code: "4009900484220",
    });
    expect(decideScanAction("12345678")).toEqual({ kind: "retail", code: "12345678" });
  });

  it("falls through to unknown for everything else", () => {
    expect(decideScanAction("hello world")).toEqual({ kind: "unknown", raw: "hello world" });
    expect(decideScanAction("123")).toEqual({ kind: "unknown", raw: "123" });
  });
});

describe("parseNdefCandidate", () => {
  it("accepts everything the strict grammar accepts", () => {
    expect(parseNdefCandidate("web+spoolman:f-5")).toMatchObject({ resource: "filament" });
  });

  it("leniently matches spool fragments like the web NFC scanner does", () => {
    expect(parseNdefCandidate("http://pi:7912/spool/show/9?utm=tag")).toMatchObject({
      resource: "spool",
      id: "9",
      path: "/spool/show/9",
    });
    expect(parseNdefCandidate("Spool at WEB+SPOOLMAN:S-33 (shelf B)")).toMatchObject({
      resource: "spool",
      id: "33",
    });
  });

  it("returns null for non-Spoolman payloads", () => {
    expect(parseNdefCandidate("https://example.com/product/9")).toBeNull();
  });
});
