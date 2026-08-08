import JSONbig from "json-bigint";

/**
 * Parse JSON while keeping integers too large for JS to represent exactly as strings, instead of
 * silently rounding them. CockroachDB's unique_rowid() primary keys exceed Number.MAX_SAFE_INTEGER,
 * and a rounded id makes the client fetch the wrong row (#69).
 *
 * json-bigint's own `storeAsString` option is NOT what implements that rule: it gates on raw
 * literal length (>15 characters), not on whether the value is actually an integer. That silently
 * turns ordinary decimal values with a long float64 representation into strings too — e.g.
 * `0.30000000000000004` (19 characters), the kind of noise that comes out of `0.1 + 0.2`-style
 * arithmetic. Once one such value is a string, `+` silently becomes concatenation everywhere it's
 * summed (home page totals, #377), corrupting the result long before anything crashes.
 *
 * So we parse with `storeAsString: false`, which makes every long literal a BigNumber instance
 * instead of a string — that's what makes it possible to tell "long numeric literal" apart from
 * "genuine string field" below. A reviver then converts each BigNumber individually: only literals
 * that are actual whole numbers beyond the safe integer range become strings (preserving the #69
 * behaviour exactly); every other value — including huge-looking decimals that are just
 * representation noise, and integers that land exactly on Number.MAX_SAFE_INTEGER — becomes a
 * normal JS number.
 */
const JSONBigNumber = JSONbig({ storeAsString: false });

/** The subset of bignumber.js's instance API the reviver below needs. */
interface BigNumberLike {
  isInteger(): boolean;
  abs(): { isGreaterThan(other: number): boolean };
  toFixed(decimalPlaces: number): string;
  toNumber(): number;
}

// bignumber.js is only a transitive dependency (pulled in by json-bigint, not declared in our own
// package.json), so it must not be imported directly here. Detect its instances instead via the
// documented `_isBigNumber` prototype flag: https://mikemcl.github.io/bignumber.js/#isBigNumber
function isBigNumber(value: unknown): value is BigNumberLike {
  return typeof value === "object" && value !== null && (value as { _isBigNumber?: unknown })._isBigNumber === true;
}

function reviveBigNumbers(_key: string, value: unknown): unknown {
  if (!isBigNumber(value)) return value;
  if (value.isInteger() && value.abs().isGreaterThan(Number.MAX_SAFE_INTEGER)) {
    // A whole number too large for JS to represent exactly (e.g. a CockroachDB spool id, #69) —
    // keep every digit as a string rather than silently rounding it to the wrong id. Comparing the
    // BigNumber directly against MAX_SAFE_INTEGER (rather than round-tripping through .toNumber()
    // first) matters: .toNumber() on a value just past the safe range can round back down to
    // exactly MAX_SAFE_INTEGER, which would wrongly look "safe" after the fact.
    return value.toFixed(0);
  }
  return value.toNumber();
}

export function parseJsonWithBigIntIds(text: string): unknown {
  return JSONBigNumber.parse(text, reviveBigNumbers);
}
