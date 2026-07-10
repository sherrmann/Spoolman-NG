import { describe, expect, it } from "vitest";
import { zipSync, strToU8 } from "fflate";
import { IFilament } from "../pages/filaments/model";
import { ISpool } from "../pages/spools/model";
import { autoMatchSpoolId, normalizeHex, parseSliceInfo, parseThreeMf, spoolPrimaryHex } from "./threeMfImport";

const SLICE_INFO = `<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="index" value="1"/>
    <filament id="1" type="PLA" color="#FF0000FF" used_m="3.45" used_g="10.5"/>
    <filament id="2" type="PETG" color="#00FF00" used_m="1.00" used_g="4.0"/>
  </plate>
  <plate>
    <metadata key="index" value="2"/>
    <filament id="1" type="PLA" color="#FF0000FF" used_m="1.00" used_g="2.5"/>
  </plate>
</config>`;

function spool(id: number, over: Partial<Omit<ISpool, "filament">> & { filament?: Partial<IFilament> } = {}): ISpool {
  const { filament: fil, ...rest } = over;
  return {
    id,
    registered: "2024-01-01T00:00:00Z",
    filament: { id, registered: "2024-01-01", density: 1.24, diameter: 1.75, extra: {}, ...fil } as IFilament,
    used_weight: 0,
    used_length: 0,
    archived: false,
    extra: {},
    ...rest,
  } as ISpool;
}

describe("normalizeHex", () => {
  it("strips the alpha and upper-cases", () => {
    expect(normalizeHex("#ff0000ff")).toBe("#FF0000");
    expect(normalizeHex("00ff00")).toBe("#00FF00");
  });
  it("returns undefined for empty or too-short values", () => {
    expect(normalizeHex(null)).toBeUndefined();
    expect(normalizeHex("#abc")).toBeUndefined();
  });
});

describe("parseSliceInfo", () => {
  it("sums a filament's usage across plates and keeps type/colour", () => {
    const result = parseSliceInfo(SLICE_INFO);
    expect(result).toEqual([
      { key: "1", type: "PLA", colorHex: "#FF0000", usedWeight: 13 },
      { key: "2", type: "PETG", colorHex: "#00FF00", usedWeight: 4 },
    ]);
  });

  it("drops filaments that consumed nothing", () => {
    const xml = '<config><plate><filament id="1" type="PLA" color="#000000" used_g="0"/></plate></config>';
    expect(parseSliceInfo(xml)).toEqual([]);
  });

  it("throws on malformed XML", () => {
    expect(() => parseSliceInfo("<config><plate>")).toThrow();
  });
});

describe("parseThreeMf", () => {
  it("unzips a 3mf and reads its slice_info.config", () => {
    const bytes = zipSync({ "Metadata/slice_info.config": strToU8(SLICE_INFO) });
    const result = parseThreeMf(bytes);
    expect(result.map((f) => f.usedWeight)).toEqual([13, 4]);
  });

  it("errors clearly when there is no slice info (an unsliced 3mf)", () => {
    const bytes = zipSync({ "3D/3dmodel.model": strToU8("<model/>") });
    expect(() => parseThreeMf(bytes)).toThrow(/no slice info/);
  });

  it("errors clearly when the bytes are not a zip", () => {
    expect(() => parseThreeMf(new Uint8Array([1, 2, 3, 4]))).toThrow(/not a valid 3mf/i);
  });
});

describe("autoMatchSpoolId", () => {
  const spools = [
    spool(1, { filament: { material: "PLA", color_hex: "FF0000" } }),
    spool(2, { filament: { material: "PETG", color_hex: "FF0000" } }),
    spool(3, { filament: { material: "PLA", color_hex: "0000FF" } }),
  ];

  it("prefers the colour match whose material also matches", () => {
    expect(autoMatchSpoolId({ key: "1", type: "PETG", colorHex: "#FF0000", usedWeight: 5 }, spools)).toBe(2);
    expect(autoMatchSpoolId({ key: "1", type: "PLA", colorHex: "#FF0000", usedWeight: 5 }, spools)).toBe(1);
  });

  it("falls back to any colour match when no material matches", () => {
    expect(autoMatchSpoolId({ key: "1", type: "TPU", colorHex: "#FF0000", usedWeight: 5 }, spools)).toBe(1);
  });

  it("returns undefined when no spool colour matches", () => {
    expect(autoMatchSpoolId({ key: "1", type: "PLA", colorHex: "#123456", usedWeight: 5 }, spools)).toBeUndefined();
  });

  it("honours a per-spool colour override over the filament colour", () => {
    const overridden = [spool(9, { color_hex: "00FF00", filament: { material: "PLA", color_hex: "FF0000" } })];
    expect(spoolPrimaryHex(overridden[0])).toBe("#00FF00");
    expect(autoMatchSpoolId({ key: "1", type: "PLA", colorHex: "#00FF00", usedWeight: 5 }, overridden)).toBe(9);
  });
});
