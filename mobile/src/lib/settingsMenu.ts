// Model for the server-settings menu (#221). Rendered by SettingsMenuModal as a real
// bottom-sheet menu: RN's Android Alert renders at most three buttons (neutral/negative/
// positive) and silently drops the rest, which made "Passkey setup" and "Change server"
// unreachable from the old 5-button Alert.

export type SettingsMenuAction = "reload" | "update-check" | "passkey-setup" | "change-server";

export interface SettingsMenuEntry {
  action: SettingsMenuAction;
  label: string;
  destructive?: boolean;
}

/** The settings menu entries for `platform` ("android" | "ios" | ...), in display order. */
export function buildSettingsMenuEntries(platform: string): SettingsMenuEntry[] {
  const entries: SettingsMenuEntry[] = [{ action: "reload", label: "Reload" }];
  if (platform === "android") {
    entries.push({ action: "update-check", label: "Check for updates" });
    entries.push({ action: "passkey-setup", label: "Passkey setup" });
  }
  entries.push({ action: "change-server", label: "Change server", destructive: true });
  return entries;
}
