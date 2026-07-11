import { describe, expect, it } from "vitest";

import { apiUrl, appUrl, normalizeBaseUrl, originOf, shouldOpenExternally } from "./serverProfile";

describe("normalizeBaseUrl", () => {
  it("defaults to http:// for bare hosts (the common LAN deployment)", () => {
    expect(normalizeBaseUrl("pi:7912")).toBe("http://pi:7912");
    expect(normalizeBaseUrl("192.168.1.10:7912")).toBe("http://192.168.1.10:7912");
  });

  it("keeps explicit schemes and sub-paths, stripping trailing slashes", () => {
    expect(normalizeBaseUrl("https://nas.example.com/spoolman/")).toBe(
      "https://nas.example.com/spoolman",
    );
    expect(normalizeBaseUrl("  http://pi:7912/  ")).toBe("http://pi:7912");
    expect(normalizeBaseUrl("HTTPS://Nas.Example.com")).toBe("HTTPS://Nas.Example.com");
  });

  it("rejects empty input, foreign schemes and malformed URLs", () => {
    expect(normalizeBaseUrl("")).toBeNull();
    expect(normalizeBaseUrl("   ")).toBeNull();
    expect(normalizeBaseUrl("ftp://pi:7912")).toBeNull();
    expect(normalizeBaseUrl("http://")).toBeNull();
    expect(normalizeBaseUrl("http://ho st")).toBeNull();
  });

  it("handles slash-heavy adversarial input in linear time (js/redos)", () => {
    // With an ambiguous repeated path group this input backtracked
    // exponentially; it must simply be rejected (the "#" is not allowed).
    expect(normalizeBaseUrl(`http://a${"/".repeat(80)}#`)).toBeNull();
    // Repeated internal slashes are odd but harmless — still accepted.
    expect(normalizeBaseUrl("http://pi:7912//spoolman///x")).toBe("http://pi:7912//spoolman///x");
  });
});

describe("URL builders", () => {
  it("compose API and app URLs against base-path deployments", () => {
    expect(apiUrl("http://pi:7912", "/info")).toBe("http://pi:7912/api/v1/info");
    expect(apiUrl("https://x.example.com/spoolman", "/nfc/lookup")).toBe(
      "https://x.example.com/spoolman/api/v1/nfc/lookup",
    );
    expect(appUrl("https://x.example.com/spoolman", "/spool/show/4")).toBe(
      "https://x.example.com/spoolman/spool/show/4",
    );
  });

  it("extracts the origin for the external-link policy", () => {
    expect(originOf("https://x.example.com/spoolman")).toBe("https://x.example.com");
    expect(originOf("http://pi:7912")).toBe("http://pi:7912");
  });
});

describe("shouldOpenExternally", () => {
  const origin = "https://spoolman-ng.sherrmann.ch";

  it("keeps same-origin, about: and data: navigations in the WebView", () => {
    expect(shouldOpenExternally(`${origin}/spool`, "click", origin)).toBe(false);
    expect(shouldOpenExternally("about:blank", "other", origin)).toBe(false);
    expect(shouldOpenExternally("data:text/html,x", "other", origin)).toBe(false);
  });

  it("keeps an off-origin forward-auth redirect in the WebView so login completes", () => {
    // The Authelia round-trip is a redirect ("other"), not a user click.
    expect(shouldOpenExternally("https://auth.sherrmann.ch/?rd=x", "other", origin)).toBe(false);
    expect(shouldOpenExternally("https://auth.sherrmann.ch/login", "formsubmit", origin)).toBe(
      false,
    );
  });

  it("sends a clicked external link to the system browser", () => {
    expect(shouldOpenExternally("https://ko-fi.com/donate", "click", origin)).toBe(true);
    expect(shouldOpenExternally("https://spoolmandb.org", "click", origin)).toBe(true);
  });
});
