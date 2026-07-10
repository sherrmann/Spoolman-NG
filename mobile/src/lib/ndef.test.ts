import { describe, expect, it } from "vitest";

import {
  decodeTextRecord,
  decodeUriRecord,
  extractTextCandidates,
  findExternalPayload,
  TNF_EXTERNAL_TYPE,
  TNF_WELL_KNOWN,
  utf8Decode,
  type NdefRecordLike,
} from "./ndef";

function utf8(s: string): number[] {
  return Array.from(Buffer.from(s, "utf-8"));
}

function uriRecord(prefixCode: number, rest: string): NdefRecordLike {
  return { tnf: TNF_WELL_KNOWN, type: "U", payload: [prefixCode, ...utf8(rest)] };
}

function textRecord(lang: string, text: string): NdefRecordLike {
  return {
    tnf: TNF_WELL_KNOWN,
    type: [0x54], // "T" as byte array, like react-native-nfc-manager delivers it
    payload: [lang.length, ...utf8(lang), ...utf8(text)],
  };
}

describe("utf8Decode", () => {
  it("decodes ascii, multi-byte sequences and emoji", () => {
    expect(utf8Decode(utf8("web+spoolman:s-42"))).toBe("web+spoolman:s-42");
    expect(utf8Decode(utf8("Überspule"))).toBe("Überspule");
    expect(utf8Decode(utf8("スプール"))).toBe("スプール");
    expect(utf8Decode(utf8("🧵"))).toBe("🧵");
  });

  it("replaces truncated or invalid sequences instead of throwing", () => {
    expect(utf8Decode([0xc3])).toBe("�"); // truncated 2-byte sequence
    expect(utf8Decode([0xff, 0x41])).toBe("�A"); // invalid lead byte
    expect(utf8Decode([0xe0, 0x41, 0x41])).toBe("�AA"); // invalid continuation
  });
});

describe("decodeUriRecord", () => {
  it("applies the RTD-URI prefix table", () => {
    expect(decodeUriRecord(uriRecord(0x04, "pi:7912/spool/show/7"))).toBe(
      "https://pi:7912/spool/show/7",
    );
    expect(decodeUriRecord(uriRecord(0x03, "pi:7912/spool/show/7"))).toBe(
      "http://pi:7912/spool/show/7",
    );
    expect(decodeUriRecord(uriRecord(0x00, "web+spoolman:s-42"))).toBe("web+spoolman:s-42");
  });

  it("rejects non-URI records and empty payloads", () => {
    expect(decodeUriRecord(textRecord("en", "x"))).toBeNull();
    expect(decodeUriRecord({ tnf: TNF_WELL_KNOWN, type: "U", payload: [] })).toBeNull();
    expect(decodeUriRecord({ tnf: 0x02, type: "U", payload: [0, 0x61] })).toBeNull();
  });
});

describe("decodeTextRecord", () => {
  it("strips the status byte and language code", () => {
    expect(decodeTextRecord(textRecord("en", "web+spoolman:s-42"))).toBe("web+spoolman:s-42");
    expect(decodeTextRecord(textRecord("de-DE", "WEB+SPOOLMAN:L-3"))).toBe("WEB+SPOOLMAN:L-3");
  });

  it("rejects UTF-16 text records and wrong types", () => {
    expect(
      decodeTextRecord({ tnf: TNF_WELL_KNOWN, type: "T", payload: [0x82, 0x65, 0x6e, 0x00, 0x41] }),
    ).toBeNull();
    expect(decodeTextRecord(uriRecord(0, "x"))).toBeNull();
  });
});

describe("extractTextCandidates", () => {
  it("collects URI and text values, skipping undecodable records", () => {
    const records: NdefRecordLike[] = [
      { tnf: TNF_EXTERNAL_TYPE, type: "tigertag.io:maker", payload: [1, 2, 3] },
      uriRecord(0x03, "pi:7912/spool/show/12"),
      textRecord("en", "web+spoolman:s-9"),
    ];
    expect(extractTextCandidates(records)).toEqual([
      "http://pi:7912/spool/show/12",
      "web+spoolman:s-9",
    ]);
  });
});

describe("findExternalPayload", () => {
  it("matches the domain:type string case-insensitively, in both type encodings", () => {
    const payload = [0xaa, 0xbb];
    expect(
      findExternalPayload(
        [{ tnf: TNF_EXTERNAL_TYPE, type: "TigerTag.io:Maker", payload }],
        "tigertag.io:maker",
      ),
    ).toEqual(payload);
    expect(
      findExternalPayload(
        [{ tnf: TNF_EXTERNAL_TYPE, type: utf8("tigertag.io:maker"), payload }],
        "tigertag.io:maker",
      ),
    ).toEqual(payload);
  });

  it("ignores other TNFs, other types and empty payloads", () => {
    expect(
      findExternalPayload(
        [{ tnf: TNF_WELL_KNOWN, type: "tigertag.io:maker", payload: [1] }],
        "tigertag.io:maker",
      ),
    ).toBeNull();
    expect(
      findExternalPayload(
        [{ tnf: TNF_EXTERNAL_TYPE, type: "example.com:other", payload: [1] }],
        "tigertag.io:maker",
      ),
    ).toBeNull();
    expect(
      findExternalPayload(
        [{ tnf: TNF_EXTERNAL_TYPE, type: "tigertag.io:maker", payload: [] }],
        "tigertag.io:maker",
      ),
    ).toBeNull();
  });
});
