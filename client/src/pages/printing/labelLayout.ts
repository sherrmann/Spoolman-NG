// Layout math for the QR label (#295), kept free of React so it is unit-testable.

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
