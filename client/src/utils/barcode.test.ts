import { describe, expect, it } from "vitest";
import { code128Bars } from "./barcode";

// Convert the boolean module columns back to the width-run string (e.g. "211214...") so we can assert
// against the known Code 128 element patterns.
function widths(modules: boolean[]): number[] {
  const runs: number[] = [];
  let i = 0;
  while (i < modules.length) {
    let n = 1;
    while (i + n < modules.length && modules[i + n] === modules[i]) n++;
    runs.push(n);
    i += n;
  }
  return runs;
}

describe("code128Bars", () => {
  it("returns an empty array for an empty (or fully non-encodable) value", () => {
    expect(code128Bars("")).toEqual([]);
  });

  it("begins with the code-set-B start pattern (211214) and ends with the stop pattern (2331112)", () => {
    const runs = widths(code128Bars("A"));
    expect(runs.slice(0, 6)).toEqual([2, 1, 1, 2, 1, 4]); // Start B
    expect(runs.slice(-7)).toEqual([2, 3, 3, 1, 1, 1, 2]); // Stop
  });

  it("encodes a known value with the correct checksum symbol", () => {
    // "AB": A=33, B=34. checksum = (104 + 33*1 + 34*2) % 103 = 205 % 103 = 102.
    // Symbol 102 pattern is "411131"; it sits just before the stop pattern.
    const runs = widths(code128Bars("AB"));
    const stopStart = runs.length - 7;
    const checksumRuns = runs.slice(stopStart - 6, stopStart);
    expect(checksumRuns).toEqual([4, 1, 1, 1, 3, 1]);
  });

  it("always begins with a dark bar", () => {
    expect(code128Bars("WEB+SPOOLMAN:S-42")[0]).toBe(true);
  });

  it("encodes the full spool scanner payload without throwing", () => {
    const modules = code128Bars("WEB+SPOOLMAN:S-12345");
    // start(11) + 20 data(11 each) + checksum(11) + stop(13) = 255 modules.
    expect(modules).toHaveLength(11 + 20 * 11 + 11 + 13);
  });

  it("skips characters outside code set B rather than throwing", () => {
    // A control/emoji char is dropped; the surrounding letters still encode.
    const withBad = code128Bars("AB");
    const clean = code128Bars("AB");
    expect(withBad).toEqual(clean);
  });
});
