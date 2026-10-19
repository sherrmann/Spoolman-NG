import {
  defaultConfig,
  type Arch,
  type Database,
  type Goal,
  type Platform,
  type Proxy,
  type SwitchDirection,
  type WizardConfig,
} from "./model/config";

/**
 * The wizard's answers as URL query parameters (#344), so a filled-in guide can be shared as a
 * support link: `…/install/?goal=fresh&platform=compose&db=postgres&klipper=1`.
 *
 * Only answers that differ from the defaults are written, which keeps links short. Reading is
 * strict: an unknown parameter or a value outside the allowed set is ignored and the default
 * kept. The free-text answers (sub-path, timezone) end up inside config files the reader pastes,
 * so a link may only carry characters those answers can legitimately contain; anything else is
 * dropped rather than passed on into a compose file.
 */

const GOALS: readonly Goal[] = ["fresh", "update", "migrate-upstream", "switch"];
const SWITCH_DIRECTIONS: readonly SwitchDirection[] = ["native-to-docker", "docker-to-native"];
const PLATFORMS: readonly Platform[] = ["compose", "native", "ha-addon", "helm", "third-party-chart"];
const DATABASES: readonly Database[] = ["sqlite", "postgres", "mysql"];
const PROXIES: readonly Proxy[] = ["none", "caddy", "nginx", "traefik"];
const ARCHES: readonly Arch[] = ["amd64", "arm64", "armv7"];

/** IANA names: "UTC", "Europe/Stockholm", "America/Argentina/Buenos_Aires", "Etc/GMT+1". A letter
 * first, so the value cannot read as a YAML list item or number. */
const TZ_PATTERN = /^[A-Za-z][A-Za-z0-9_+-]*(\/[A-Za-z0-9_+-]+)*$/;
/** URL path characters only; normalizeSubPath adds the leading slash later. */
const SUB_PATH_PATTERN = /^[A-Za-z0-9._~/-]+$/;
const MAX_TEXT = 64;
const MAX_ID = 2 ** 31 - 1;

function pick<T extends string>(value: string | null, allowed: readonly T[]): T | undefined {
  return allowed.find((item) => item === value);
}

function text(raw: string | null, pattern: RegExp): string | null {
  // The form keeps what was typed and trims at plan time; trim here too, so a trailing space
  // does not cost the link its answer.
  const value = raw?.trim() ?? null;
  if (value === null || value.length > MAX_TEXT || !pattern.test(value)) return null;
  // Neither answer has "." or ".." segments; a link that does is not one the guide wrote.
  if (value.split("/").some((segment) => segment === "." || segment === "..")) return null;
  return value;
}

function id(value: string | null): number | null {
  if (value === null || !/^\d{1,10}$/.test(value)) return null;
  const n = Number(value);
  return n <= MAX_ID ? n : null;
}

function flag(params: URLSearchParams, key: string): boolean {
  return params.get(key) === "1";
}

/** Read wizard answers from a query string; anything missing or invalid keeps its default. */
export function configFromSearch(search: string): WizardConfig {
  const params = new URLSearchParams(search);
  const d = defaultConfig;
  const puid = id(params.get("puid"));
  const pgid = id(params.get("pgid"));
  return {
    goal: pick(params.get("goal"), GOALS) ?? d.goal,
    switchDirection: pick(params.get("switch"), SWITCH_DIRECTIONS) ?? d.switchDirection,
    platform: pick(params.get("platform"), PLATFORMS) ?? d.platform,
    klipper: flag(params, "klipper"),
    database: pick(params.get("db"), DATABASES) ?? d.database,
    proxy: pick(params.get("proxy"), PROXIES) ?? d.proxy,
    subPath: text(params.get("path"), SUB_PATH_PATTERN),
    installedBefore20260719: flag(params, "before"),
    extras: {
      nfc: flag(params, "nfc"),
      apiToken: flag(params, "token"),
      tz: text(params.get("tz"), TZ_PATTERN),
      puidPgid: puid !== null && pgid !== null ? { puid, pgid } : null,
      ai: flag(params, "ai"),
      arch: pick(params.get("arch"), ARCHES) ?? d.extras.arch,
    },
  };
}

/** Write wizard answers as a query string (no leading "?"); defaults are left out. */
export function searchFromConfig(config: WizardConfig): string {
  const d = defaultConfig;
  const params = new URLSearchParams();
  const set = (key: string, value: string, fallback: string) => {
    if (value !== fallback) params.set(key, value);
  };
  const setFlag = (key: string, value: boolean) => {
    if (value) params.set(key, "1");
  };
  set("goal", config.goal, d.goal);
  set("switch", config.switchDirection, d.switchDirection);
  set("platform", config.platform, d.platform);
  setFlag("klipper", config.klipper);
  set("db", config.database, d.database);
  set("proxy", config.proxy, d.proxy);
  if (config.subPath) params.set("path", config.subPath);
  setFlag("before", config.installedBefore20260719);
  setFlag("nfc", config.extras.nfc);
  setFlag("token", config.extras.apiToken);
  if (config.extras.tz) params.set("tz", config.extras.tz);
  if (config.extras.puidPgid) {
    params.set("puid", String(config.extras.puidPgid.puid));
    params.set("pgid", String(config.extras.puidPgid.pgid));
  }
  setFlag("ai", config.extras.ai);
  set("arch", config.extras.arch, d.extras.arch);
  return params.toString();
}
