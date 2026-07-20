import { describe, expect, it } from "vitest";
import { getBasePath, safeHttpUrl } from "./url";

// Regression tests for the sub-path service-worker / deep-link fixes (PRs #26/#29):
// the SW URL, manifest scope and print links are all built by prefixing getBasePath().
// Oracle: the documented contract ("" at root, "/spoolman" under a sub-path) and the
// absolute URLs derived from it — not the implementation.
describe("getBasePath", () => {
  it("returns an empty string when SPOOLMAN_BASE_PATH is unset", () => {
    expect(getBasePath()).toBe("");
  });

  it("returns an empty string when SPOOLMAN_BASE_PATH is empty", () => {
    window.SPOOLMAN_BASE_PATH = "";
    expect(getBasePath()).toBe("");
  });

  it("returns the configured base path under a sub-path deploy", () => {
    window.SPOOLMAN_BASE_PATH = "/spoolman";
    expect(getBasePath()).toBe("/spoolman");
  });

  it("yields an absolute root-level service-worker URL when unset", () => {
    // Mirrors index.tsx: register(`${getBasePath()}/sw.js`, { scope: `${getBasePath()}/` }).
    expect(`${getBasePath()}/sw.js`).toBe("/sw.js");
    expect(`${getBasePath()}/`).toBe("/");
  });

  it("yields a base-path-prefixed service-worker URL under a sub-path", () => {
    window.SPOOLMAN_BASE_PATH = "/spoolman";
    // The bug resolved a relative "./sw.js" to "/spool/sw.js" on deep links → 404.
    expect(`${getBasePath()}/sw.js`).toBe("/spoolman/sw.js");
    expect(`${getBasePath()}/`).toBe("/spoolman/");
  });
});

// Guards against stored-XSS via user-supplied order/shop URLs (e.g. orders.url) rendered as
// `<a href>`: React does not sanitize hrefs, so a `javascript:` or `data:` scheme would otherwise
// become a clickable script. Oracle: only http/https URLs that survive `new URL()` parsing pass.
describe("safeHttpUrl", () => {
  it("passes through a valid https URL", () => {
    expect(safeHttpUrl("https://example.com/order/123")).toBe("https://example.com/order/123");
  });

  it("passes through a valid http URL", () => {
    expect(safeHttpUrl("http://example.com/order/123")).toBe("http://example.com/order/123");
  });

  it("rejects a javascript: URL", () => {
    expect(safeHttpUrl("javascript:alert(1)")).toBeUndefined();
  });

  it("rejects a data: URL", () => {
    expect(safeHttpUrl("data:text/html,<script>alert(1)</script>")).toBeUndefined();
  });

  it("rejects a garbage/unparseable string", () => {
    expect(safeHttpUrl("not a url")).toBeUndefined();
  });

  it("passes through undefined unchanged", () => {
    expect(safeHttpUrl(undefined)).toBeUndefined();
  });
});
