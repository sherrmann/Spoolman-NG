import { afterEach, describe, expect, it, vi } from "vitest";

import { ForwardAuthError } from "../lib/forwardAuth";
import { ApiError, probeServer } from "./spoolman";

// #222: redirect-style forward-auth gateways (nginx auth_request with error_page 302,
// Authentik embedded outpost) answer /info with a redirect that fetch follows to the
// portal's 200 HTML login page. The detector supports that shape (status 200 + off-origin
// finalUrl / portal markers), but the plumbing only fed it ApiError (!ok) failures — a 200
// HTML page surfaced as a raw JSON-parse error instead of the portal flow.

const BASE = "http://spool.local:7912";

function htmlResponse(url: string, body: string): Response {
  return {
    ok: true,
    status: 200,
    url,
    text: async () => body,
    json: async () => JSON.parse(body),
  } as unknown as Response;
}

function jsonResponse(url: string, body: unknown): Response {
  return {
    ok: true,
    status: 200,
    url,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("probeServer forward-auth detection (#222)", () => {
  it("routes a 200 HTML portal page reached via redirect to the ForwardAuthError flow", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => htmlResponse("https://auth.example.com/?rd=http://spool.local:7912", "<html>Sign in</html>")),
    );

    await expect(probeServer(BASE)).rejects.toBeInstanceOf(ForwardAuthError);
  });

  it("routes a same-origin 200 page naming a known portal to the ForwardAuthError flow", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => htmlResponse(`${BASE}/api/v1/info`, "<html><title>Authelia</title></html>")),
    );

    await expect(probeServer(BASE)).rejects.toBeInstanceOf(ForwardAuthError);
  });

  it("surfaces a same-origin non-JSON page without portal signals as a typed ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => htmlResponse(`${BASE}/api/v1/info`, "<html>this is not spoolman</html>")),
    );

    await expect(probeServer(BASE)).rejects.toBeInstanceOf(ApiError);
  });

  it("still resolves a healthy server", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        String(url).includes("/auth/status")
          ? jsonResponse(String(url), { accounts_enabled: false })
          : jsonResponse(String(url), { version: "2026.7.10" }),
      ),
    );

    const result = await probeServer(BASE);
    expect(result.info.version).toBe("2026.7.10");
  });
});
