// Minimal base64 encoder for raw tag dumps. Hermes does not guarantee
// btoa/Buffer, and the payloads are tiny (<= a few hundred bytes), so a pure
// implementation beats a dependency.

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

export function bytesToBase64(bytes: ArrayLike<number>): string {
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i] & 0xff;
    const hasB1 = i + 1 < bytes.length;
    const hasB2 = i + 2 < bytes.length;
    const b1 = hasB1 ? bytes[i + 1] & 0xff : 0;
    const b2 = hasB2 ? bytes[i + 2] & 0xff : 0;
    out += ALPHABET[b0 >> 2];
    out += ALPHABET[((b0 & 0x03) << 4) | (b1 >> 4)];
    out += hasB1 ? ALPHABET[((b1 & 0x0f) << 2) | (b2 >> 6)] : "=";
    out += hasB2 ? ALPHABET[b2 & 0x3f] : "=";
  }
  return out;
}
