import { describe, expect, it } from "vitest";
import { ScanTarget } from "./scan";
import { decideScan } from "./scanMove";

const spool = (id: string): ScanTarget => ({ resource: "spool", id, path: `/spool/show/${id}` });
const filament = (id: string): ScanTarget => ({ resource: "filament", id, path: `/filament/show/${id}` });
const location = (id: string): ScanTarget => ({ resource: "location", id, path: `/location/show/${id}` });

describe("decideScan (#84 scan-to-move)", () => {
  it("navigates in open mode regardless of resource", () => {
    expect(decideScan("open", null, spool("5"))).toEqual({ kind: "navigate", path: "/spool/show/5" });
    expect(decideScan("open", null, location("2"))).toEqual({ kind: "navigate", path: "/location/show/2" });
  });

  it("ignores an unrecognised code in either mode", () => {
    expect(decideScan("open", null, null)).toEqual({ kind: "ignore" });
    expect(decideScan("move", null, null)).toEqual({ kind: "ignore" });
    expect(decideScan("move", 5, null)).toEqual({ kind: "ignore" });
  });

  it("captures a spool as the first move scan", () => {
    expect(decideScan("move", null, spool("5"))).toEqual({ kind: "capture_spool", spoolId: 5 });
  });

  it("asks for a spool when the first move scan is not a spool", () => {
    expect(decideScan("move", null, location("2"))).toEqual({ kind: "need_spool" });
    expect(decideScan("move", null, filament("9"))).toEqual({ kind: "need_spool" });
  });

  it("proposes the move when a location is scanned after a spool", () => {
    expect(decideScan("move", 5, location("2"))).toEqual({ kind: "propose_move", spoolId: 5, locationId: 2 });
  });

  it("ignores the same spool still in view while awaiting a location", () => {
    expect(decideScan("move", 5, spool("5"))).toEqual({ kind: "ignore" });
  });

  it("asks for a location when a different spool or a filament is scanned second", () => {
    expect(decideScan("move", 5, spool("6"))).toEqual({ kind: "need_location" });
    expect(decideScan("move", 5, filament("9"))).toEqual({ kind: "need_location" });
  });
});
