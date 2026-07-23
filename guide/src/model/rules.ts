import { effectivePlatform, normalizeSubPath, type WizardConfig } from "./config";
import type { Note } from "./types";

/** Docs placeholder for the Moonraker [spoolman] server URL (kept identical to installation.md). */
export const SPOOLMAN_URL_PLACEHOLDER = "http://<spoolman-host>:7912";

export interface NormalizedConfig {
  /** Input config with cross-cutting rules applied (never mutates the input). */
  effective: WizardConfig;
  warnings: Note[];
}

/**
 * Apply the rules that change the *effective* configuration before any artifact
 * or step is generated, and collect plan-wide warnings.
 */
export function normalizeConfig(input: WizardConfig): NormalizedConfig {
  const warnings: Note[] = [];
  const effective: WizardConfig = {
    ...input,
    platform: effectivePlatform(input),
    subPath: normalizeSubPath(input.subPath),
    ai: { ...input.ai },
    extras: { ...input.extras, puidPgid: input.extras.puidPgid ? { ...input.extras.puidPgid } : null },
  };

  // AI provisioning (#364) only exists where the wizard controls the runtime.
  const aiApplies =
    (effective.goal === "fresh" || effective.goal === "switch") &&
    (effective.platform === "compose" || effective.platform === "native");
  if (!aiApplies) {
    effective.ai.choice = "none";
  }

  // Hardware gate: there is no 32-bit ARM Ollama build, and Pi-3-class hardware
  // cannot hold a useful model in RAM. Refuse the sidecar loudly and steer to a
  // remote endpoint instead of shipping a compose file that cannot work.
  if (effective.ai.choice === "local" && effective.ai.arch === "arm32") {
    effective.ai.choice = "remote";
    warnings.push({
      level: "warning",
      id: "ai-sidecar-refused-armv7",
      text:
        "Local AI skipped: Ollama has no 32-bit ARM (armv7) build, and this class of hardware cannot " +
        "hold a useful model in memory. Spoolman itself runs fine here — point Settings → AI at an " +
        "Ollama running on another machine on your network (a desktop PC or NAS is one URL away), or " +
        "at a cloud provider. See docs/ai.md.",
    });
  }

  // #268: Moonraker's [spoolman] component has no auth option, so an API token
  // silently breaks Klipper filament tracking. Drop it and say so loudly.
  if (effective.klipper && effective.extras.apiToken) {
    effective.extras.apiToken = false;
    warnings.push({
      level: "warning",
      id: "token-dropped-for-klipper",
      text:
        "API token omitted: Moonraker's [spoolman] component cannot send a token, so setting " +
        "SPOOLMAN_API_TOKEN would silently break Klipper filament tracking (#268). Keep this instance " +
        "token-free on the trusted LAN — use user accounts for the web UI, or gate external access at a " +
        "reverse proxy/VPN with an unauthenticated path for printer traffic.",
    });
  }

  // The one-click updater only applies to native installs; the flag is asked only there.
  if (effective.platform !== "native" || !effective.klipper || effective.goal !== "update") {
    effective.installedBefore20260719 = false;
  }

  if (effective.goal === "migrate-upstream") {
    warnings.push({
      level: "warning",
      id: "backup-before-migrating",
      text:
        "Back up your database before migrating. Spoolman-NG migrates the schema automatically on first " +
        "start, and a backup is the way back.",
    });
  }

  if (effective.goal === "update") {
    warnings.push({
      level: "info",
      id: "backup-before-updating",
      text: "Upgrades apply database migrations automatically on startup — take a backup first so you can roll back.",
    });
  }

  return { effective, warnings };
}

/** Rule 3: the Moonraker [update_manager] recipe applies to native installs only. */
export function wantsUpdateManager(effective: WizardConfig): boolean {
  return effective.klipper && effective.platform === "native";
}

/**
 * Rule 4 (pairing): serving under a sub-path on Kubernetes must set the base
 * path AND move the health-probe path together — a single code path produces
 * both so one can never ship without the other.
 */
export function helmSubPathPairing(subPath: string): { basePath: string; probePath: string } {
  return { basePath: subPath, probePath: `${subPath}/api/v1/health` };
}
