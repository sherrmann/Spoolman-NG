// One tag-read session: acquire the tag, harvest NDEF candidates, and dump raw
// memory for the server's /nfc/lookup auto-detection — the same contract the
// Klipper NFC daemons use (docs/nfc.md).
//
// P0 scope: NDEF on any tag plus raw NTAG213 reads (TigerTag). ISO 15693
// (OpenPrintTag) and MIFARE Classic (Qidi) raw reads are the next phase — see
// docs/mobile-companion-app.md.

import { Platform } from "react-native";
import NfcManager, { NfcTech } from "react-native-nfc-manager";

import { extractTextCandidates, findExternalPayload, type NdefRecordLike } from "../lib/ndef";

export const TIGERTAG_EXTERNAL_TYPE = "tigertag.io:maker";

// NTAG213 user memory: pages 4..39 inclusive, 4 bytes each = 144 bytes — what
// spoolman/nfc_service.py reads and what /nfc/encode emits.
const NTAG_FIRST_PAGE = 0x04;
const NTAG_LAST_PAGE = 0x27;
const NTAG_DUMP_BYTES = (NTAG_LAST_PAGE - NTAG_FIRST_PAGE + 1) * 4;

export interface TagReadResult {
  /** Lowercase hex UID, if the platform reported one. */
  uidHex: string | null;
  /** Decoded URI/Text record values (may contain web+spoolman: payloads). */
  textCandidates: string[];
  /** Payload of a TigerTag NDEF external record, if present. */
  tigertagPayload: number[] | null;
  /** Raw user-memory dump (NTAG213 pages 4-39), if the tag allowed it. */
  rawDump: number[] | null;
}

let started: Promise<void> | null = null;

/** Idempotent NfcManager.start(); resolves false when the device has no NFC. */
export async function ensureNfcStarted(): Promise<boolean> {
  try {
    if (!(await NfcManager.isSupported())) {
      return false;
    }
    if (!started) {
      started = NfcManager.start();
    }
    await started;
    return true;
  } catch {
    started = null;
    return false;
  }
}

export async function isNfcEnabled(): Promise<boolean> {
  if (Platform.OS !== "android") {
    return true; // Android-only concept; iOS has no user toggle to query
  }
  try {
    return await NfcManager.isEnabled();
  } catch {
    return false;
  }
}

function transceive(bytes: number[]): Promise<number[]> {
  if (Platform.OS === "ios") {
    return NfcManager.sendMifareCommandIOS(bytes);
  }
  return NfcManager.nfcAHandler.transceive(bytes);
}

async function readNtagUserMemory(): Promise<number[] | null> {
  // FAST_READ (0x3A, start, end) pulls pages 4-39 in one shot on NTAG21x.
  try {
    const data = await transceive([0x3a, NTAG_FIRST_PAGE, NTAG_LAST_PAGE]);
    if (data.length >= NTAG_DUMP_BYTES) {
      return data.slice(0, NTAG_DUMP_BYTES);
    }
  } catch {
    /* fall back to plain READs */
  }
  // READ (0x30, page) returns 16 bytes (4 pages); step through the range.
  const dump: number[] = [];
  try {
    for (let page = NTAG_FIRST_PAGE; page <= NTAG_LAST_PAGE; page += 4) {
      const chunk = await transceive([0x30, page]);
      if (chunk.length < 16) {
        return null;
      }
      dump.push(...chunk.slice(0, 16));
    }
  } catch {
    return null;
  }
  return dump.length >= NTAG_DUMP_BYTES ? dump.slice(0, NTAG_DUMP_BYTES) : null;
}

/**
 * Run one scan session and gather everything the caller might need. Resolves
 * once a tag was read; rejects on cancel/session errors. Always releases the
 * session.
 */
export async function readSpoolmanTag(): Promise<TagReadResult> {
  const techs =
    Platform.OS === "ios" ? [NfcTech.MifareIOS, NfcTech.Ndef] : [NfcTech.NfcA, NfcTech.Ndef];
  const tech = await NfcManager.requestTechnology(techs, {
    alertMessage: "Hold your phone near the spool tag",
  });
  try {
    const tag = await NfcManager.getTag();
    const records = (tag?.ndefMessage ?? []) as NdefRecordLike[];
    const uidHex = tag?.id ? tag.id.toLowerCase() : null;
    const textCandidates = extractTextCandidates(records);
    const tigertagPayload = findExternalPayload(records, TIGERTAG_EXTERNAL_TYPE);

    // Raw page reads need the low-level tech; when the session resolved as
    // plain Ndef (non-Type-2 tags), the transceive would fail anyway.
    let rawDump: number[] | null = null;
    const lowLevel = tech === NfcTech.NfcA || tech === NfcTech.MifareIOS;
    if (lowLevel) {
      rawDump = await readNtagUserMemory();
    }
    return { uidHex, textCandidates, tigertagPayload, rawDump };
  } finally {
    NfcManager.cancelTechnologyRequest().catch(() => {});
  }
}

export async function cancelNfcRead(): Promise<void> {
  await NfcManager.cancelTechnologyRequest().catch(() => {});
}

/** Android: open the system NFC settings pane. No-op elsewhere. */
export async function openNfcSettings(): Promise<void> {
  if (Platform.OS === "android") {
    await NfcManager.goToNfcSetting().catch(() => {});
  }
}
