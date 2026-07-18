import { describe, expect, it } from "vitest";

import { buildSettingsMenuEntries } from "./settingsMenu";

// #221: RN's Android Alert renders at most 3 buttons and silently drops the rest, which hid
// "Passkey setup" and "Change server" — the settings menu is now a real menu driven by this
// model. These tests pin that every action is present per platform, in order.

describe("buildSettingsMenuEntries", () => {
  it("android gets all four actions, Change server destructive and last", () => {
    const entries = buildSettingsMenuEntries("android");
    expect(entries.map((e) => e.action)).toEqual(["reload", "update-check", "passkey-setup", "change-server"]);
    const last = entries[entries.length - 1];
    expect(last.action).toBe("change-server");
    expect(last.destructive).toBe(true);
  });

  it("ios gets reload and change-server only (update/passkey flows are Android-only)", () => {
    expect(buildSettingsMenuEntries("ios").map((e) => e.action)).toEqual(["reload", "change-server"]);
  });

  it("every entry has a non-empty label", () => {
    for (const platform of ["android", "ios"]) {
      for (const entry of buildSettingsMenuEntries(platform)) {
        expect(entry.label.length).toBeGreaterThan(0);
      }
    }
  });
});
