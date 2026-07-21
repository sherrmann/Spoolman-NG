// Layout math for the QR label (#295), kept free of React so it is unit-testable.

import type { PrintSettings } from "./printing";

// Below roughly this printed size a QR becomes unreliable for phone cameras at arm's
// length; the size control soft-warns under it rather than blocking (dedicated
// scanners and short payloads can go smaller).
export const MIN_SCANNABLE_QR_MM = 10;

// Starting size when the user switches the QR from Auto to Custom, and the fallback when
// the number input is cleared. Comfortably above the scannability floor.
export const DEFAULT_QR_SIZE_MM = 20;

// The flex basis of the QR container along the item's main axis. No manual size keeps
// the historical fill behavior: half the label when text/swatch/barcode show beside it,
// the whole label otherwise (#59). A manual size is the printed QR square, so the
// qrPadding quiet zone is added back on both sides; the min() cap keeps an oversized
// setting from overflowing the label.
export function qrContainerBasis(opts: { showSide: boolean; qrSize?: number; qrPadding: number }): string {
  const { showSide, qrSize, qrPadding } = opts;
  if (!qrSize || qrSize <= 0) {
    return showSide ? "50%" : "100%";
  }
  // Round to 0.1mm so float artifacts (12.3 + 0.2 = 12.499...) don't leak into the CSS.
  const total = Math.round((qrSize + 2 * qrPadding) * 10) / 10;
  return `min(${total}mm, 100%)`;
}

export interface PaperDimensions {
  width: number;
  height: number;
}

export const paperDimensions: { [key: string]: PaperDimensions } = {
  A3: {
    width: 297,
    height: 420,
  },
  A4: {
    width: 210,
    height: 297,
  },
  A5: {
    width: 148,
    height: 210,
  },
  Letter: {
    width: 216,
    height: 279,
  },
  Legal: {
    width: 216,
    height: 356,
  },
  Tabloid: {
    width: 279,
    height: 432,
  },
  // Curated single-label sizes for thermal/roll label printers (#141). Selecting one and setting
  // columns/rows to 1 (plus "Match label" page size, #71) prints a single label at true geometry.
  "Label 89×36 mm": {
    width: 89,
    height: 36,
  },
  "Label 62×29 mm": {
    width: 62,
    height: 29,
  },
  "Label 57×32 mm": {
    width: 57,
    height: 32,
  },
  "Label 50×30 mm": {
    width: 50,
    height: 30,
  },
  "Label 40×30 mm": {
    width: 40,
    height: 30,
  },
};

export function resolvePaperSize(settings?: PrintSettings): PaperDimensions {
  const paperSize = settings?.paperSize || "A4";
  if (paperSize === "custom") {
    return settings?.customPaperSize || { width: 210, height: 297 };
  }
  // A named size a future version dropped (stale preset) degrades to A4 instead of crashing.
  return paperDimensions[paperSize] ?? paperDimensions.A4;
}

// The mm size of one label cell on the sheet. Must apply the same defaults and formula as the
// page renderer in printingDialog (which calls this), so anything derived from it — like the
// rendered-QR readout below — can never disagree with what actually prints.
export function labelCellSize(settings?: PrintSettings): { width: number; height: number } {
  const margin = settings?.margin || { top: 10, bottom: 10, left: 10, right: 10 };
  const spacing = settings?.spacing || { horizontal: 0, vertical: 0 };
  const columns = settings?.columns || 3;
  const rows = settings?.rows || 8;
  const paper = resolvePaperSize(settings);
  return {
    width: (paper.width - margin.left - margin.right - spacing.horizontal) / columns - spacing.horizontal,
    height: (paper.height - margin.top - margin.bottom - spacing.vertical) / rows - spacing.vertical,
  };
}

// The QR square that actually prints (#296). The container basis is min(qrSize + 2·padding,
// cell main axis), the cross axis is the full cell, and object-fit: contain letterboxes the
// square SVG to the padded box — so the printed side collapses to the smallest of: the request,
// and each cell axis minus both quiet zones. Placement (left/top/bottom) only swaps which axis
// the basis applies to; the min over both axes makes the result placement-independent.
// Approximation, hence the "≈" in the UI copy: the 1px grid border and the printer-margin
// padding on edge cells shave up to ~0.3mm more in those specific cells.
export function renderedQrSize(opts: {
  qrSize: number;
  qrPadding: number;
  cellWidth: number;
  cellHeight: number;
}): number {
  const { qrSize, qrPadding, cellWidth, cellHeight } = opts;
  const side = Math.min(qrSize, cellWidth - 2 * qrPadding, cellHeight - 2 * qrPadding);
  // Round to 0.1mm for display; also forgives sub-0.05mm clamps so "20 set, 19.98 rendered"
  // doesn't warn.
  return Math.max(0, Math.round(side * 10) / 10);
}
