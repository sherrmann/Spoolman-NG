import { describe, expect, it } from "vitest";

import { bytesToBase64 } from "./base64";

function utf8Bytes(s: string): number[] {
  return Array.from(Buffer.from(s, "utf-8"));
}

describe("bytesToBase64", () => {
  it("matches the RFC 4648 test vectors", () => {
    expect(bytesToBase64([])).toBe("");
    expect(bytesToBase64(utf8Bytes("f"))).toBe("Zg==");
    expect(bytesToBase64(utf8Bytes("fo"))).toBe("Zm8=");
    expect(bytesToBase64(utf8Bytes("foo"))).toBe("Zm9v");
    expect(bytesToBase64(utf8Bytes("foob"))).toBe("Zm9vYg==");
    expect(bytesToBase64(utf8Bytes("fooba"))).toBe("Zm9vYmE=");
    expect(bytesToBase64(utf8Bytes("foobar"))).toBe("Zm9vYmFy");
  });

  it("agrees with Buffer for all byte values and NTAG-sized payloads", () => {
    const allBytes = Array.from({ length: 256 }, (_, i) => i);
    expect(bytesToBase64(allBytes)).toBe(Buffer.from(allBytes).toString("base64"));

    // 144 bytes = NTAG213 pages 4-39, the TigerTag payload size.
    const dump = Array.from({ length: 144 }, (_, i) => (i * 37) % 256);
    expect(bytesToBase64(dump)).toBe(Buffer.from(dump).toString("base64"));
  });

  it("masks values outside the byte range like a typed array would", () => {
    expect(bytesToBase64([256 + 65])).toBe(bytesToBase64([65]));
  });
});
