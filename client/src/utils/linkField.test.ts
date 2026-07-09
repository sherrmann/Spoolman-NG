import { describe, expect, it } from "vitest";
import { buildLinkUrl } from "./linkField";

describe("buildLinkUrl (#129)", () => {
  it("substitutes the value into a {} placeholder", () => {
    expect(buildLinkUrl("https://www.amazon.com/dp/{}", "B0ABCDEF")).toBe("https://www.amazon.com/dp/B0ABCDEF");
  });

  it("appends the value when there is no placeholder", () => {
    expect(buildLinkUrl("https://example.com/part/", "12345")).toBe("https://example.com/part/12345");
  });

  it("substitutes into every placeholder occurrence", () => {
    expect(buildLinkUrl("https://x/{}?ref={}", "abc")).toBe("https://x/abc?ref=abc");
  });

  it("URL-encodes the value", () => {
    expect(buildLinkUrl("https://x/{}", "a b/c")).toBe("https://x/a%20b%2Fc");
  });

  it("returns an empty string for an empty value (no link)", () => {
    expect(buildLinkUrl("https://x/{}", "")).toBe("");
  });
});
