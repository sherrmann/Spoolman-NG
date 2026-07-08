// Minimal Code 128 (code set B) encoder for optional 1D barcodes on printed labels (#138).
//
// Code set B covers all printable ASCII 32–126, which includes every character in the
// `WEB+SPOOLMAN:S-<id>` / `WEB+SPOOLMAN:F-<id>` scanner payloads and the deep-link URL form, so the
// same value used for the QR code can be encoded as a 1D barcode alongside it. This is print-only:
// there is no in-app decoder, so no round-trip requirement — a standard Code 128 reader decodes it.

// Standard Code 128 element-width patterns, indexed by symbol value. Each entry is a run of
// bar/space widths (starting with a bar) summing to 11 modules; the stop pattern (106) is 13.
const PATTERNS = [
  "212222",
  "222122",
  "222221",
  "121223",
  "121322",
  "131222",
  "122213",
  "122312",
  "132212",
  "221213",
  "221312",
  "231212",
  "112232",
  "122132",
  "122231",
  "113222",
  "123122",
  "123221",
  "223211",
  "221132",
  "221231",
  "213212",
  "223112",
  "312131",
  "311222",
  "321122",
  "321221",
  "312212",
  "322112",
  "322211",
  "212123",
  "212321",
  "232121",
  "111323",
  "131123",
  "131321",
  "112313",
  "132113",
  "132311",
  "211313",
  "231113",
  "231311",
  "112133",
  "112331",
  "132131",
  "113123",
  "113321",
  "133121",
  "313121",
  "211331",
  "231131",
  "213113",
  "213311",
  "213131",
  "311123",
  "311321",
  "331121",
  "312113",
  "312311",
  "332111",
  "314111",
  "221411",
  "431111",
  "111224",
  "111422",
  "121124",
  "121421",
  "141122",
  "141221",
  "112214",
  "112412",
  "122114",
  "122411",
  "142112",
  "142211",
  "241211",
  "221114",
  "413111",
  "241112",
  "134111",
  "111242",
  "121142",
  "121241",
  "114212",
  "124112",
  "124211",
  "411212",
  "421112",
  "421211",
  "212141",
  "214121",
  "412121",
  "111143",
  "111341",
  "131141",
  "114113",
  "114311",
  "411113",
  "411311",
  "113141",
  "114131",
  "311141",
  "411131",
  "211412",
  "211214",
  "211232",
  "2331112",
];

const START_B = 104;
const STOP = 106;

/**
 * Encode `value` as Code 128 (set B) and return its module columns: one boolean per 1-module-wide
 * column, `true` = dark bar. A caller renders these as `<rect>`s (one per run) to draw the barcode.
 * Characters outside code set B are skipped defensively rather than throwing, so a stray tag never
 * breaks the whole print. An empty result (no encodable characters) yields an empty array.
 */
export function code128Bars(value: string): boolean[] {
  const codes: number[] = [];
  for (const ch of value) {
    const v = ch.charCodeAt(0) - 32;
    if (v >= 0 && v < 95) {
      codes.push(v);
    }
  }
  if (codes.length === 0) {
    return [];
  }

  // Checksum: start value plus each data value weighted by its 1-based position, modulo 103.
  let checksum = START_B;
  codes.forEach((c, i) => {
    checksum += c * (i + 1);
  });
  checksum %= 103;

  const symbols = [START_B, ...codes, checksum, STOP];
  const modules: boolean[] = [];
  for (const sym of symbols) {
    const widths = PATTERNS[sym];
    let bar = true; // every pattern begins with a bar
    for (const w of widths) {
      const count = Number(w);
      for (let i = 0; i < count; i++) {
        modules.push(bar);
      }
      bar = !bar;
    }
  }
  return modules;
}
