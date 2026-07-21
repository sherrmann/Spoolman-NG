import { describe, expect, it } from "vitest";
import { fragmentNames, fragmentPlaceholders, renderFragment } from "./fragments";

/** Documented example values, matching docs/installation.md exactly (drift-tested there). */
export const DOCS_DEFAULTS: Record<string, Record<string, string>> = {
  "caddy.Caddyfile": { HOSTNAME: "spoolman.example.com", UPSTREAM: "localhost:7912" },
  "kiauh-install.sh": {},
  "moonraker-spoolman.ini": { SPOOLMAN_URL: "http://<spoolman-host>:7912" },
  "moonraker-update-manager.ini": {},
  "native-install.sh": {},
  "native-update.sh": {},
  "nginx-location.conf": { UPSTREAM: "127.0.0.1:7912" },
  "release-info-fix.sh": {},
};

describe("fragments", () => {
  it("ships exactly the documented set", () => {
    expect(fragmentNames()).toEqual(Object.keys(DOCS_DEFAULTS).sort());
  });

  it("every fragment renders with its documented defaults, leaving no placeholders", () => {
    for (const [name, vars] of Object.entries(DOCS_DEFAULTS)) {
      const rendered = renderFragment(name, vars);
      expect(rendered).not.toMatch(/\{\{[A-Z0-9_]+\}\}/);
      expect(rendered.length).toBeGreaterThan(0);
    }
  });

  it("declared defaults cover each fragment's placeholders exactly", () => {
    for (const [name, vars] of Object.entries(DOCS_DEFAULTS)) {
      expect([...new Set(fragmentPlaceholders(name))].sort()).toEqual(Object.keys(vars).sort());
    }
  });

  it("throws on an unknown fragment", () => {
    expect(() => renderFragment("nope.ini")).toThrow(/Unknown fragment/);
  });

  it("throws when a placeholder value is missing", () => {
    expect(() => renderFragment("moonraker-spoolman.ini")).toThrow(/missing value for \{\{SPOOLMAN_URL\}\}/);
  });

  it("throws when a variable is passed that the fragment does not use", () => {
    expect(() => renderFragment("moonraker-update-manager.ini", { BOGUS: "x" })).toThrow(/does not appear/);
  });
});
