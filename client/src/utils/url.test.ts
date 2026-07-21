import { describe, expect, it } from "vitest";
import { getBasePath, isHaIngress, safeHttpUrl } from "./url";

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

  it("follows an HA ingress session prefix like any other base path", () => {
    // Under HA ingress config.js hands the client the rotating session prefix (#211);
    // router, API and websocket URLs are all derived from it via getBasePath().
    window.SPOOLMAN_BASE_PATH = "/api/hassio_ingress/50j2apJ8Ny_kCT9dr8kHYWNSYAlJqZlx";
    expect(getBasePath()).toBe("/api/hassio_ingress/50j2apJ8Ny_kCT9dr8kHYWNSYAlJqZlx");
  });
});

// Under HA ingress the base path carries a rotating per-session token, so index.tsx must
// skip service-worker registration (a SW scope cannot follow the token). Oracle: the flag
// is only true when the backend's config.js explicitly set it — every other shape of the
// global (absent, false, truthy garbage from an extension) means "not ingress", keeping
// the PWA fully alive on direct origins.
describe("isHaIngress", () => {
  it("is false when the global is unset (every non-ingress deployment)", () => {
    expect(isHaIngress()).toBe(false);
  });

  it("is true only when config.js set the flag to true", () => {
    window.SPOOLMAN_HA_INGRESS = true;
    expect(isHaIngress()).toBe(true);
  });

  it("is false for a non-boolean truthy value", () => {
    (window as unknown as { SPOOLMAN_HA_INGRESS: unknown }).SPOOLMAN_HA_INGRESS = "1";
    expect(isHaIngress()).toBe(false);
  });

  it("gates the index.tsx service-worker registration condition", () => {
    // Mirrors index.tsx: register only when `"serviceWorker" in navigator && !isHaIngress()`.
    window.SPOOLMAN_HA_INGRESS = true;
    window.SPOOLMAN_BASE_PATH = "/api/hassio_ingress/50j2apJ8Ny_kCT9dr8kHYWNSYAlJqZlx";
    expect(!isHaIngress()).toBe(false); // ingress: skip registration
    delete window.SPOOLMAN_HA_INGRESS;
    expect(!isHaIngress()).toBe(true); // direct origin: register as before
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
