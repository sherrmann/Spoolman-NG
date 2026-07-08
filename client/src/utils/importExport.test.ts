import { describe, expect, it } from "vitest";
import { exportFilename, importEntityOf, importSucceeded, type ImportResult } from "./importExport";

describe("importExport helpers", () => {
  it("maps a plural export entity to its singular import entity", () => {
    expect(importEntityOf("vendors")).toBe("vendor");
    expect(importEntityOf("filaments")).toBe("filament");
    expect(importEntityOf("spools")).toBe("spool");
  });

  it("builds a deterministic download filename", () => {
    expect(exportFilename("filaments", "csv")).toBe("spoolman-filaments.csv");
    expect(exportFilename("spools", "json")).toBe("spoolman-spools.json");
  });

  it("treats an import as successful only when there are no errors", () => {
    const base: ImportResult = { created: 1, updated: 0, skipped: 0, dry_run: false, errors: [] };
    expect(importSucceeded(base)).toBe(true);
    expect(importSucceeded({ ...base, errors: ["Row 0: bad"] })).toBe(false);
  });
});
