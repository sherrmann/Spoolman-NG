import { describe, expect, it } from "vitest";
import { labelCellSize, MIN_SCANNABLE_QR_MM, qrContainerBasis, renderedQrSize, resolvePaperSize } from "./labelLayout";
import { PrintSettings } from "./printing";

const settings = (overrides: Partial<PrintSettings>): PrintSettings => ({ id: "test", ...overrides });

// The QR container's flex basis decides how much of the label the QR occupies (#295).
// Auto keeps the historical fill behavior (half the label beside content, all of it
// alone); a manual size in mm becomes a definite basis of QR + quiet zone, capped at
// the label so an oversized setting can't blow up the layout.
describe("qrContainerBasis", () => {
  it("auto fills half the label when content shows beside the QR", () => {
    expect(qrContainerBasis({ showSide: true, qrSize: undefined, qrPadding: 2 })).toBe("50%");
  });

  it("auto fills the whole label when the QR stands alone", () => {
    expect(qrContainerBasis({ showSide: false, qrSize: undefined, qrPadding: 2 })).toBe("100%");
  });

  it("a manual size reserves the QR plus its padding on both sides, capped at the label", () => {
    expect(qrContainerBasis({ showSide: true, qrSize: 14, qrPadding: 2 })).toBe("min(18mm, 100%)");
  });

  it("a manual size without padding is just the QR square", () => {
    expect(qrContainerBasis({ showSide: false, qrSize: 14, qrPadding: 0 })).toBe("min(14mm, 100%)");
  });

  it("a zero/invalid manual size falls back to auto", () => {
    expect(qrContainerBasis({ showSide: true, qrSize: 0, qrPadding: 2 })).toBe("50%");
    expect(qrContainerBasis({ showSide: true, qrSize: -3, qrPadding: 2 })).toBe("50%");
  });

  it("fractional sizes survive without float noise", () => {
    expect(qrContainerBasis({ showSide: true, qrSize: 12.3, qrPadding: 0.1 })).toBe("min(12.5mm, 100%)");
  });
});

describe("MIN_SCANNABLE_QR_MM", () => {
  it("is the ~10mm phone-camera floor the size warning keys off", () => {
    expect(MIN_SCANNABLE_QR_MM).toBe(10);
  });
});

// Cell geometry shared between the page renderer and the rendered-QR readout (#296). The
// formula must mirror printingDialog exactly — including its quirk of subtracting spacing
// once before dividing and once after — or the readout would lie about what prints.
describe("labelCellSize", () => {
  it("defaults to the A4 3×8 grid with 10mm margins", () => {
    const cell = labelCellSize(undefined);
    expect(cell.width).toBeCloseTo(190 / 3, 10);
    expect(cell.height).toBeCloseTo(34.625, 10);
  });

  it("a single-label layout on label paper is the full paper", () => {
    const cell = labelCellSize(
      settings({
        paperSize: "Label 62×29 mm",
        margin: { top: 0, bottom: 0, left: 0, right: 0 },
        columns: 1,
        rows: 1,
      }),
    );
    expect(cell).toEqual({ width: 62, height: 29 });
  });

  it("subtracts spacing once from the sheet and once per cell, like the page layout", () => {
    const cell = labelCellSize(
      settings({
        paperSize: "custom",
        customPaperSize: { width: 100, height: 100 },
        margin: { top: 0, bottom: 0, left: 0, right: 0 },
        spacing: { horizontal: 2, vertical: 4 },
        columns: 2,
        rows: 2,
      }),
    );
    expect(cell).toEqual({ width: 47, height: 44 });
  });
});

describe("resolvePaperSize", () => {
  it("custom size wins over the named table", () => {
    expect(resolvePaperSize(settings({ paperSize: "custom", customPaperSize: { width: 80, height: 40 } }))).toEqual({
      width: 80,
      height: 40,
    });
  });

  it("an unknown named size degrades to A4 instead of crashing on a stale preset", () => {
    expect(resolvePaperSize(settings({ paperSize: "B5" }))).toEqual({ width: 210, height: 297 });
  });
});

// The printed QR square (#296): the smallest of the request and each cell axis minus both
// quiet zones — the same collapse min()+object-fit performs in CSS, made readable so the
// size control can warn when the label can't deliver the requested size.
describe("renderedQrSize", () => {
  it("returns the requested size when the cell fits it", () => {
    expect(renderedQrSize({ qrSize: 20, qrPadding: 2, cellWidth: 58, cellHeight: 25 })).toBe(20);
  });

  it("clamps to the cell height minus the quiet zones", () => {
    expect(renderedQrSize({ qrSize: 20, qrPadding: 2, cellWidth: 62, cellHeight: 12 })).toBe(8);
  });

  it("clamps to the cell width minus the quiet zones", () => {
    expect(renderedQrSize({ qrSize: 20, qrPadding: 2, cellWidth: 10, cellHeight: 40 })).toBe(6);
  });

  it("an exactly-fitting cell does not count as clamped", () => {
    expect(renderedQrSize({ qrSize: 20, qrPadding: 2, cellWidth: 24, cellHeight: 24 })).toBe(20);
  });

  it("never goes negative when padding exceeds the cell", () => {
    expect(renderedQrSize({ qrSize: 20, qrPadding: 2, cellWidth: 3, cellHeight: 3 })).toBe(0);
  });

  it("rounds to 0.1mm for display", () => {
    expect(renderedQrSize({ qrSize: 20, qrPadding: 2, cellWidth: 62, cellHeight: 12.34 })).toBe(8.3);
  });

  it("zero padding uses the full cell", () => {
    expect(renderedQrSize({ qrSize: 30, qrPadding: 0, cellWidth: 25, cellHeight: 40 })).toBe(25);
  });
});
