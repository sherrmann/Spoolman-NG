export type Goal = "fresh" | "update" | "migrate-upstream" | "switch";
export type SwitchDirection = "native-to-docker" | "docker-to-native";
export type Platform = "compose" | "native" | "ha-addon" | "helm" | "third-party-chart";
export type Database = "sqlite" | "postgres" | "mysql";
export type Proxy = "none" | "caddy" | "nginx" | "traefik";

/** AI features (#364): none, a local Ollama provisioned alongside, or a remote endpoint. */
export type AIChoice = "none" | "local" | "remote";
/** CPU architecture of the machine that would run the local AI runtime. */
export type AIArch = "amd64" | "arm64" | "arm32";

export interface AIOptions {
  choice: AIChoice;
  /** Only meaningful when choice === "local"; drives hardware gating and expectation copy. */
  arch: AIArch;
}

export interface Extras {
  /** Server-side USB NFC reader (docs/nfc.md). */
  nfc: boolean;
  /** SPOOLMAN_API_TOKEN — dropped with a warning when Klipper is selected (#268). */
  apiToken: boolean;
  /** IANA timezone name, e.g. "Europe/Stockholm"; null = leave at the UTC default. */
  tz: string | null;
  /** Docker-only uid/gid of the in-container user owning the data volume. */
  puidPgid: { puid: number; pgid: number } | null;
}

export interface WizardConfig {
  goal: Goal;
  /** Only meaningful when goal === "switch"; determines the effective platform. */
  switchDirection: SwitchDirection;
  platform: Platform;
  klipper: boolean;
  database: Database;
  proxy: Proxy;
  /** Serve under a sub-path, e.g. "/spoolman". null = served at the root. */
  subPath: string | null;
  /** Native install set up before 2026-07-19 (release_info.json fix, docs/installation.md). */
  installedBefore20260719: boolean;
  ai: AIOptions;
  extras: Extras;
}

export const defaultConfig: WizardConfig = {
  goal: "fresh",
  switchDirection: "native-to-docker",
  platform: "compose",
  klipper: false,
  database: "sqlite",
  proxy: "none",
  subPath: null,
  installedBefore20260719: false,
  ai: { choice: "none", arch: "amd64" },
  extras: { nfc: false, apiToken: false, tz: null, puidPgid: null },
};

/** The platform the generated plan targets (goal "switch" implies it). */
export function effectivePlatform(config: WizardConfig): Platform {
  if (config.goal === "switch") {
    return config.switchDirection === "native-to-docker" ? "compose" : "native";
  }
  return config.platform;
}

/** Ensure a leading slash, no trailing slash; null for empty/root input. */
export function normalizeSubPath(raw: string | null): string | null {
  if (!raw) return null;
  let path = raw.trim();
  if (!path || path === "/") return null;
  if (!path.startsWith("/")) path = `/${path}`;
  return path.replace(/\/+$/, "");
}

export type QuestionId =
  | "goal"
  | "switchDirection"
  | "platform"
  | "klipper"
  | "database"
  | "proxy"
  | "subPath"
  | "installedBefore20260719"
  | "ai"
  | "extras";

/**
 * Which questions actually influence the generated plan for a given goal/platform.
 * The UI disables the rest so answers never silently do nothing.
 */
export function relevantQuestions(config: WizardConfig): Set<QuestionId> {
  const platform = effectivePlatform(config);
  const relevant = new Set<QuestionId>(["goal", "klipper"]);
  if (config.goal === "switch") {
    relevant.add("switchDirection");
  } else {
    relevant.add("platform");
  }
  switch (config.goal) {
    case "fresh":
    case "switch":
      relevant.add("database");
      relevant.add("extras");
      // AI provisioning (#364) applies where the wizard controls the runtime: Compose
      // (sidecar) and native (install.sh --with-ai). Helm/add-on users bring their own.
      if (platform === "compose" || platform === "native") {
        relevant.add("ai");
      }
      if (platform !== "ha-addon" && config.goal !== "switch") {
        relevant.add("proxy");
        relevant.add("subPath");
      }
      break;
    case "migrate-upstream":
      relevant.add("database");
      break;
    case "update":
      if (platform === "native" && config.klipper) {
        relevant.add("installedBefore20260719");
      }
      break;
  }
  // The HA add-on configures database/proxy/extras in its own options UI.
  if (platform === "ha-addon" || platform === "third-party-chart") {
    relevant.delete("database");
    relevant.delete("extras");
    relevant.delete("proxy");
    if (platform === "ha-addon") relevant.delete("subPath");
  }
  return relevant;
}
