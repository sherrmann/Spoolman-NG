import { describe, expect, it } from "vitest";

import {
  buildAssetlinksJson,
  LOGIN_CREDS_RELATION,
  normalizeFingerprint,
  responseWarnings,
  verifyAssetlinks,
  wellKnownUrl,
} from "./assetlinks";

const PKG = "app.spoolman.companion";
const FP = Array(32).fill("AB").join(":");
const OTHER_FP = Array(32).fill("CD").join(":");

function statement(overrides?: Partial<{ relation: unknown; target: Record<string, unknown> }>) {
  return {
    relation: [LOGIN_CREDS_RELATION],
    target: {
      namespace: "android_app",
      package_name: PKG,
      sha256_cert_fingerprints: [FP],
    },
    ...overrides,
  };
}

describe("normalizeFingerprint", () => {
  it("uppercases and trims", () => {
    expect(normalizeFingerprint("  ab:cd ")).toBe("AB:CD");
  });
});

describe("buildAssetlinksJson", () => {
  it("renders a single get_login_creds statement with normalized fingerprints", () => {
    const parsed = JSON.parse(buildAssetlinksJson(PKG, [FP.toLowerCase()]));
    expect(parsed).toEqual([
      {
        relation: [LOGIN_CREDS_RELATION],
        target: {
          namespace: "android_app",
          package_name: PKG,
          sha256_cert_fingerprints: [FP],
        },
      },
    ]);
  });

  it("is pretty-printed for copy-paste", () => {
    expect(buildAssetlinksJson(PKG, [FP])).toContain("\n  ");
  });
});

describe("wellKnownUrl", () => {
  it("builds the URL from a bare hostname", () => {
    expect(wellKnownUrl("auth.example.com")).toBe(
      "https://auth.example.com/.well-known/assetlinks.json",
    );
  });

  it("extracts the host from a full URL with path and query", () => {
    expect(wellKnownUrl("https://auth.example.com/?rd=https%3A%2F%2Fx")).toBe(
      "https://auth.example.com/.well-known/assetlinks.json",
    );
  });

  it("keeps a port and lowercases the host", () => {
    expect(wellKnownUrl("HTTPS://Auth.Example.com:8443/login")).toBe(
      "https://auth.example.com:8443/.well-known/assetlinks.json",
    );
  });

  it("always uses https even for http input", () => {
    expect(wellKnownUrl("http://auth.example.com")).toBe(
      "https://auth.example.com/.well-known/assetlinks.json",
    );
  });

  it("rejects empty input and non-http schemes", () => {
    expect(wellKnownUrl("")).toBeNull();
    expect(wellKnownUrl("   ")).toBeNull();
    expect(wellKnownUrl("ftp://auth.example.com")).toBeNull();
    expect(wellKnownUrl("://nope")).toBeNull();
  });
});

describe("verifyAssetlinks", () => {
  it("passes for a well-formed statement matching package and fingerprint", () => {
    expect(verifyAssetlinks([statement()], PKG, [FP])).toEqual({ ok: true, problems: [] });
  });

  it("matches fingerprints case-insensitively", () => {
    const payload = [statement()];
    expect(verifyAssetlinks(payload, PKG, [FP.toLowerCase()]).ok).toBe(true);
  });

  it("skips the fingerprint check when installed fingerprints are unknown", () => {
    expect(verifyAssetlinks([statement()], PKG, []).ok).toBe(true);
  });

  it("fails when the payload is not an array", () => {
    const verdict = verifyAssetlinks({ relation: [] }, PKG, [FP]);
    expect(verdict.ok).toBe(false);
    expect(verdict.problems[0]).toMatch(/not a JSON array/);
  });

  it("fails when no statement targets the package", () => {
    const other = statement();
    other.target = { ...other.target, package_name: "com.other.app" };
    const verdict = verifyAssetlinks([other], PKG, [FP]);
    expect(verdict.ok).toBe(false);
    expect(verdict.problems[0]).toContain(PKG);
  });

  it("fails when the relation is missing get_login_creds", () => {
    const verdict = verifyAssetlinks(
      [statement({ relation: ["delegate_permission/common.handle_all_urls"] })],
      PKG,
      [FP],
    );
    expect(verdict.ok).toBe(false);
    expect(verdict.problems[0]).toContain(LOGIN_CREDS_RELATION);
  });

  it("fails when no fingerprint matches, naming the installed one", () => {
    const verdict = verifyAssetlinks([statement()], PKG, [OTHER_FP]);
    expect(verdict.ok).toBe(false);
    expect(verdict.problems[0]).toContain(OTHER_FP);
  });

  it("fails when the statement lists no fingerprints", () => {
    const bare = statement();
    bare.target = { namespace: "android_app", package_name: PKG };
    const verdict = verifyAssetlinks([bare], PKG, [FP]);
    expect(verdict.ok).toBe(false);
    expect(verdict.problems[0]).toMatch(/no sha256_cert_fingerprints/);
  });

  it("accepts a passing statement among unrelated ones", () => {
    const web = { relation: [LOGIN_CREDS_RELATION], target: { namespace: "web", site: "https://x" } };
    expect(verifyAssetlinks([web, statement()], PKG, [FP]).ok).toBe(true);
  });
});

describe("responseWarnings", () => {
  const url = "https://auth.example.com/.well-known/assetlinks.json";

  it("is quiet for a direct application/json response", () => {
    expect(
      responseWarnings({ requestedUrl: url, finalUrl: url, contentType: "application/json; charset=utf-8" }),
    ).toEqual([]);
  });

  it("warns on redirects", () => {
    const warnings = responseWarnings({
      requestedUrl: url,
      finalUrl: "https://cdn.example.com/assetlinks.json",
      contentType: "application/json",
    });
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toMatch(/redirect/i);
  });

  it("ignores a trailing-slash-only difference", () => {
    expect(responseWarnings({ requestedUrl: url, finalUrl: `${url}/` })).toEqual([]);
  });

  it("warns on a wrong content type", () => {
    const warnings = responseWarnings({ requestedUrl: url, finalUrl: url, contentType: "text/html" });
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("text/html");
  });

  it("stays quiet when metadata is unavailable", () => {
    expect(responseWarnings({ requestedUrl: url })).toEqual([]);
  });
});
