// Decision logic for a scanned value (camera or NFC). The payload grammar is
// the web client's own — vendored byte-identically from client/src/utils/scan.ts
// (see scripts/sync-shared.mjs), not reimplemented, so app and printed labels
// can never drift apart.

import {
  isClearScan,
  looksLikeRetailBarcode,
  parseScanResult,
  type ScanTarget,
} from "../shared/scan";

export type { ScanTarget };

export type ScanAction =
  | { kind: "navigate"; target: ScanTarget }
  | { kind: "clear" }
  | { kind: "retail"; code: string }
  | { kind: "unknown"; raw: string };

export function decideScanAction(raw: string): ScanAction {
  const value = raw.trim();
  if (isClearScan(value)) {
    return { kind: "clear" };
  }
  const target = parseScanResult(value);
  if (target) {
    return { kind: "navigate", target };
  }
  if (looksLikeRetailBarcode(value)) {
    return { kind: "retail", code: value };
  }
  return { kind: "unknown", raw: value };
}

// NFC text/URI payloads written by third parties are messier than printed QR
// codes (extra query strings, unanchored fragments). Mirror the web NFC
// scanner's lenient fallbacks (nfcScannerModal.tsx) after the strict grammar.
const LENIENT_SPOOL_SCHEME = /web\+spoolman:s-(\d+)/i;
const LENIENT_SPOOL_URL = /\/spool\/show\/(\d+)/i;

export function parseNdefCandidate(raw: string): ScanTarget | null {
  const value = raw.trim();
  const strict = parseScanResult(value);
  if (strict) {
    return strict;
  }
  const match = value.match(LENIENT_SPOOL_SCHEME) ?? value.match(LENIENT_SPOOL_URL);
  if (match) {
    return { resource: "spool", id: match[1], path: `/spool/show/${match[1]}` };
  }
  return null;
}
