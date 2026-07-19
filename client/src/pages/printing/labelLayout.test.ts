import { describe, expect, it } from "vitest";
import { MIN_SCANNABLE_QR_MM, qrContainerBasis } from "./labelLayout";

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
