import { describe, expect, it } from "vitest";

import {
  buildNavigateScript,
  buildStartupInjection,
  parseWebViewMessage,
  TOKEN_MESSAGE_TYPE,
} from "./inject";

describe("buildStartupInjection", () => {
  it("seeds the web client's exact localStorage key with the raw token", () => {
    const script = buildStartupInjection("abc123");
    expect(script).toContain('localStorage.setItem("spoolmanApiToken","abc123")');
    expect(script.endsWith("true;")).toBe(true);
  });

  it("escapes tokens that contain quotes and backslashes", () => {
    const nasty = 'to"ken\\end';
    const script = buildStartupInjection(nasty);
    expect(script).toContain(JSON.stringify(nasty));
    // Constructing a Function parses (but does not run) the script — a
    // botched escape would make this throw a SyntaxError.
    expect(() => new Function(script)).not.toThrow();
  });

  it("does not clear a webview-side login when the shell has no token", () => {
    const script = buildStartupInjection(null);
    expect(script).not.toContain("setItem");
    expect(script).not.toContain("removeItem");
    expect(script).toContain("getItem");
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
  it("round-trips what the injected mirror posts", () => {
    const posted = JSON.stringify({ type: TOKEN_MESSAGE_TYPE, token: "tok" });
    expect(parseWebViewMessage(posted)).toEqual({ type: TOKEN_MESSAGE_TYPE, token: "tok" });
  });

  it("maps a cleared token to null and ignores foreign messages", () => {
    expect(
      parseWebViewMessage(JSON.stringify({ type: TOKEN_MESSAGE_TYPE, token: null })),
    ).toEqual({ type: TOKEN_MESSAGE_TYPE, token: null });
    expect(parseWebViewMessage(JSON.stringify({ type: "other" }))).toBeNull();
    expect(parseWebViewMessage("not json")).toBeNull();
  });
});
