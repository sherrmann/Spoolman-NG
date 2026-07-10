// Pure NDEF record decoding, shaped after react-native-nfc-manager's record
// objects ({tnf, type, payload}). Kept free of native imports so the decode
// rules are unit-testable; the thin reader in src/nfc feeds records in.

export interface NdefRecordLike {
  tnf: number;
  type: number[] | string;
  payload: ArrayLike<number>;
}

export const TNF_WELL_KNOWN = 0x01;
export const TNF_EXTERNAL_TYPE = 0x04;

// NFC Forum URI Record Type Definition prefix table (RTD-URI section 3.2.2).
const URI_PREFIXES = [
  "",
  "http://www.",
  "https://www.",
  "http://",
  "https://",
  "tel:",
  "mailto:",
  "ftp://anonymous:anonymous@",
  "ftp://ftp.",
  "ftps://",
  "sftp://",
  "smb://",
  "nfs://",
  "ftp://",
  "dav://",
  "news:",
  "telnet://",
  "imap:",
  "rtsp://",
  "urn:",
  "pop:",
  "sip:",
  "sips:",
  "tftp:",
  "btspp://",
  "btl2cap://",
  "btgoep://",
  "tcpobex://",
  "irdaobex://",
  "file://",
  "urn:epc:id:",
  "urn:epc:tag:",
  "urn:epc:pat:",
  "urn:epc:raw:",
  "urn:epc:",
  "urn:nfc:",
];

function toByteArray(value: ArrayLike<number>): number[] {
  return Array.from(value, (b) => b & 0xff);
}

function typeAsString(type: number[] | string): string {
  return typeof type === "string" ? type : String.fromCharCode(...type);
}

/** Strict-enough UTF-8 decoder (TextDecoder is not guaranteed on Hermes). */
export function utf8Decode(bytes: ArrayLike<number>): string {
  const b = toByteArray(bytes);
  let out = "";
  let i = 0;
  while (i < b.length) {
    const byte = b[i];
    let codePoint: number;
    let extra: number;
    if (byte < 0x80) {
      codePoint = byte;
      extra = 0;
    } else if ((byte & 0xe0) === 0xc0) {
      codePoint = byte & 0x1f;
      extra = 1;
    } else if ((byte & 0xf0) === 0xe0) {
      codePoint = byte & 0x0f;
      extra = 2;
    } else if ((byte & 0xf8) === 0xf0) {
      codePoint = byte & 0x07;
      extra = 3;
    } else {
      out += "�";
      i += 1;
      continue;
    }
    if (i + extra >= b.length) {
      out += "�";
      break;
    }
    let valid = true;
    for (let k = 1; k <= extra; k += 1) {
      const cont = b[i + k];
      if ((cont & 0xc0) !== 0x80) {
        valid = false;
        break;
      }
      codePoint = (codePoint << 6) | (cont & 0x3f);
    }
    if (!valid) {
      out += "�";
      i += 1;
      continue;
    }
    out += String.fromCodePoint(codePoint);
    i += extra + 1;
  }
  return out;
}

/** Decode a Well-Known URI record ("U") to its full URI, or null. */
export function decodeUriRecord(record: NdefRecordLike): string | null {
  if (record.tnf !== TNF_WELL_KNOWN || typeAsString(record.type) !== "U") {
    return null;
  }
  const payload = toByteArray(record.payload);
  if (payload.length === 0) {
    return null;
  }
  const prefix = URI_PREFIXES[payload[0]] ?? "";
  return prefix + utf8Decode(payload.slice(1));
}

/** Decode a Well-Known Text record ("T") to its text, or null (UTF-16 unsupported). */
export function decodeTextRecord(record: NdefRecordLike): string | null {
  if (record.tnf !== TNF_WELL_KNOWN || typeAsString(record.type) !== "T") {
    return null;
  }
  const payload = toByteArray(record.payload);
  if (payload.length === 0) {
    return null;
  }
  const status = payload[0];
  if ((status & 0x80) !== 0) {
    return null; // UTF-16 encoded text records don't occur in Spoolman payloads
  }
  const languageLength = status & 0x3f;
  return utf8Decode(payload.slice(1 + languageLength));
}

/**
 * All URI/Text record values on the tag — the candidates that may contain a
 * `web+spoolman:` payload or a deep-link URL.
 */
export function extractTextCandidates(records: readonly NdefRecordLike[]): string[] {
  const out: string[] = [];
  for (const record of records) {
    const value = decodeUriRecord(record) ?? decodeTextRecord(record);
    if (value) {
      out.push(value);
    }
  }
  return out;
}

/**
 * Payload bytes of an External Type record matching `domainType` (e.g.
 * "tigertag.io:maker", as written by the TigerTag app and the web client's
 * NDEF write path), or null.
 */
export function findExternalPayload(
  records: readonly NdefRecordLike[],
  domainType: string,
): number[] | null {
  const wanted = domainType.toLowerCase();
  for (const record of records) {
    if (record.tnf !== TNF_EXTERNAL_TYPE) {
      continue;
    }
    if (typeAsString(record.type).toLowerCase() !== wanted) {
      continue;
    }
    const payload = toByteArray(record.payload);
    if (payload.length > 0) {
      return payload;
    }
  }
  return null;
}
