import { describe, expect, it } from "vitest";

import { extractAuthUrl, looksLikeForwardAuth } from "./forwardAuth";

const AUTHELIA_BODY =
  '<a href="https://auth.sherrmann.ch/?rd=https%3A%2F%2Fspoolman-ng.sherrmann.ch%2Fapi%2Fv1%2Finfo&amp;rm=GET">401 Unauthorized</a>';

describe("looksLikeForwardAuth", () => {
  it("treats a 401/403 on the public /info as a gateway wall", () => {
    // Spoolman never protects /info, so these can only come from something
    // sitting in front of it.
    expect(
      looksLikeForwardAuth({ status: 401, baseUrl: "https://spoolman-ng.sherrmann.ch" }),
    ).toBe(true);
    expect(
      looksLikeForwardAuth({ status: 403, baseUrl: "https://spoolman-ng.sherrmann.ch" }),
    ).toBe(true);
  });

  it("detects a redirect to a different origin", () => {
    expect(
      looksLikeForwardAuth({
        status: 200,
        finalUrl: "https://auth.sherrmann.ch/",
        baseUrl: "https://spoolman-ng.sherrmann.ch",
      }),
    ).toBe(true);
  });

  it("detects a known portal named in the body", () => {
    expect(
      looksLikeForwardAuth({
        status: 200,
        body: "<html><title>Authelia</title></html>",
        baseUrl: "https://spoolman-ng.sherrmann.ch",
      }),
    ).toBe(true);
  });

  it("does not misfire on a genuine failure to the same origin", () => {
    // 404/500 with no portal signal is a real server problem, not a wall.
    expect(
      looksLikeForwardAuth({ status: 404, baseUrl: "https://spoolman-ng.sherrmann.ch" }),
    ).toBe(false);
    expect(
      looksLikeForwardAuth({
        status: 500,
        body: "Internal Server Error",
        finalUrl: "https://spoolman-ng.sherrmann.ch/api/v1/info",
        baseUrl: "https://spoolman-ng.sherrmann.ch",
      }),
    ).toBe(false);
  });
});

describe("extractAuthUrl", () => {
  it("recovers the portal URL from an Authelia body and decodes HTML entities", () => {
    // The href is returned verbatim apart from HTML entities (&amp; -> &); the
    // percent-encoded rd= query value is left intact.
    expect(extractAuthUrl(AUTHELIA_BODY)).toBe(
      "https://auth.sherrmann.ch/?rd=https%3A%2F%2Fspoolman-ng.sherrmann.ch%2Fapi%2Fv1%2Finfo&rm=GET",
    );
  });

  it("falls back to an rd= redirect parameter", () => {
    expect(
      extractAuthUrl("Redirecting to /portal?rd=https%3A%2F%2Fsso.example.com%2Flogin"),
    ).toBe("https://sso.example.com/login");
  });

  it("does not double-unescape entities (ampersand decoded last)", () => {
    // A pre-escaped "&amp;quot;" must decode to the literal text "&quot;",
    // never to '"' — otherwise it is a double-unescape (CodeQL js/double-escaping).
    const body = 'href="https://sso.example.com/?next=a&amp;quot;b"';
    expect(extractAuthUrl(body)).toBe("https://sso.example.com/?next=a&quot;b");
  });

  it("returns null for a body with no recoverable URL", () => {
    expect(extractAuthUrl("401 Unauthorized")).toBeNull();
    expect(extractAuthUrl(undefined)).toBeNull();
  });
});
