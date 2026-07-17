import { describe, expect, it, vi } from "vitest";

import {
  buildNavigateScript,
  buildStartupInjection,
  normalizeOrigin,
  parseWebViewMessage,
  TOKEN_MESSAGE_TYPE,
} from "./inject";

const ORIGIN = "http://pi:7912";

/**
 * Execute the injected script against a stubbed page environment so origin
 * gating is tested behaviorally, not by string matching. Only the globals the
 * script actually touches are provided.
 */
function runInjection(script: string, pageOrigin: string) {
  const setItem = vi.fn();
  const getItem = vi.fn(() => null);
  const setInterval = vi.fn();
  const fn = new Function("localStorage", "location", "window", "setInterval", script);
  fn({ setItem, getItem }, { origin: pageOrigin }, {}, setInterval);
  return { setItem, setInterval };
}

describe("buildStartupInjection", () => {
  it("seeds the web client's exact localStorage key with the raw token", () => {
    const script = buildStartupInjection("abc123", ORIGIN);
    expect(script).toContain('localStorage.setItem("spoolmanApiToken","abc123")');
    expect(script.endsWith("true;")).toBe(true);
  });

  it("escapes tokens that contain quotes and backslashes", () => {
    const nasty = 'to"ken\\end';
    const script = buildStartupInjection(nasty, ORIGIN);
    expect(script).toContain(JSON.stringify(nasty));
    // Constructing a Function parses (but does not run) the script — a
    // botched escape would make this throw a SyntaxError.
    expect(() => new Function(script)).not.toThrow();
  });

  it("does not clear a webview-side login when the shell has no token", () => {
    const script = buildStartupInjection(null, ORIGIN);
    expect(script).not.toContain("setItem");
    expect(script).not.toContain("removeItem");
    expect(script).toContain("getItem");
  });

  // #220: the script runs on every navigation, including forward-auth portals and
  // IdPs that load in-WebView. The token must never touch a foreign origin's
  // localStorage, and the mirror must not run there either.
  it("seeds the token on the configured server origin", () => {
    const { setItem, setInterval } = runInjection(buildStartupInjection("tok", ORIGIN), "http://pi:7912");
    expect(setItem).toHaveBeenCalledWith("spoolmanApiToken", "tok");
    expect(setInterval).toHaveBeenCalled();
  });

  it("does not seed the token or start the mirror on a foreign origin (#220)", () => {
    const { setItem, setInterval } = runInjection(buildStartupInjection("tok", ORIGIN), "https://auth.example.com");
    expect(setItem).not.toHaveBeenCalled();
    expect(setInterval).not.toHaveBeenCalled();
  });

  it("matches origins case-insensitively and across default ports (#220)", () => {
    // location.origin is always lowercase and omits default ports; the profile
    // baseUrl may not be. The guard must compare the normalized forms.
    const { setItem } = runInjection(buildStartupInjection("tok", "HTTP://Pi:80"), "http://pi");
    expect(setItem).toHaveBeenCalledWith("spoolmanApiToken", "tok");
  });
});

describe("normalizeOrigin (#220)", () => {
  it("lowercases scheme and host and strips default ports", () => {
    expect(normalizeOrigin("HTTP://Pi:80")).toBe("http://pi");
    expect(normalizeOrigin("https://Example.COM:443")).toBe("https://example.com");
    expect(normalizeOrigin("http://pi:7912")).toBe("http://pi:7912");
  });

  it("returns unrecognized values unchanged (fail-closed comparison)", () => {
    expect(normalizeOrigin("not-a-url")).toBe("not-a-url");
  });
});

describe("buildNavigateScript", () => {
  it("JSON-escapes the URL", () => {
    expect(buildNavigateScript("http://pi:7912/spool/show/4")).toBe(
      'location.assign("http://pi:7912/spool/show/4");true;',
    );
    expect(buildNavigateScript('http://x/"quote')).toContain('\\"quote');
  });
});

describe("parseWebViewMessage", () => {
  it("round-trips what the injected mirror posts from the server origin", () => {
    const posted = JSON.stringify({ type: TOKEN_MESSAGE_TYPE, token: "tok" });
    expect(parseWebViewMessage(posted, "http://pi:7912/spool/show/4", ORIGIN)).toEqual({
      type: TOKEN_MESSAGE_TYPE,
      token: "tok",
    });
  });

  it("maps a cleared token to null and ignores foreign messages", () => {
    expect(
      parseWebViewMessage(JSON.stringify({ type: TOKEN_MESSAGE_TYPE, token: null }), `${ORIGIN}/`, ORIGIN),
    ).toEqual({ type: TOKEN_MESSAGE_TYPE, token: null });
    expect(parseWebViewMessage(JSON.stringify({ type: "other" }), `${ORIGIN}/`, ORIGIN)).toBeNull();
    expect(parseWebViewMessage("not json", `${ORIGIN}/`, ORIGIN)).toBeNull();
  });

  // #220: any page in the WebView can postMessage — a foreign page must not be able
  // to overwrite or clear the stored token.
  it("rejects token messages posted from a foreign origin (#220)", () => {
    const posted = JSON.stringify({ type: TOKEN_MESSAGE_TYPE, token: "evil" });
    expect(parseWebViewMessage(posted, "https://auth.example.com/portal", ORIGIN)).toBeNull();
  });

  it("accepts messages across origin case/default-port differences (#220)", () => {
    const posted = JSON.stringify({ type: TOKEN_MESSAGE_TYPE, token: "tok" });
    expect(parseWebViewMessage(posted, "http://pi/page", "HTTP://Pi:80")).toEqual({
      type: TOKEN_MESSAGE_TYPE,
      token: "tok",
    });
  });
});
