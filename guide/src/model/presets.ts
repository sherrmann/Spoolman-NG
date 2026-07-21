import { defaultConfig, type Extras, type WizardConfig } from "./config";

export interface Preset {
  id: string;
  label: string;
  config: WizardConfig;
}

type PresetOverrides = Omit<Partial<WizardConfig>, "extras"> & { extras?: Partial<Extras> };

function preset(id: string, label: string, overrides: PresetOverrides): Preset {
  return {
    id,
    label,
    config: {
      ...defaultConfig,
      ...overrides,
      extras: { ...defaultConfig.extras, ...(overrides.extras ?? {}) },
    },
  };
}

/**
 * Representative configurations covering every generator branch at least once.
 * Shared by the snapshot tests and scripts/render-matrix.ts — CI renders each
 * one and runs `docker compose config` / `helm template` on the outputs.
 */
export const presets: Preset[] = [
  // Mirrors the canonical root docker-compose.yml (drift-tested against it).
  preset("compose-sqlite-default", "Docker Compose, SQLite (the quick start)", {
    extras: { tz: "Europe/Stockholm" },
  }),
  preset(
    "compose-postgres-traefik-subpath-klipper",
    "Compose + Postgres + Traefik sub-path + Klipper (token dropped)",
    {
      database: "postgres",
      proxy: "traefik",
      subPath: "/spoolman",
      klipper: true,
      extras: { apiToken: true },
    },
  ),
  preset("compose-mysql-nfc-puid-tz", "Compose + MySQL + NFC reader + PUID/PGID + TZ", {
    database: "mysql",
    extras: { nfc: true, puidPgid: { puid: 1000, pgid: 1000 }, tz: "Europe/Berlin" },
  }),
  preset("compose-sqlite-caddy-token", "Compose + Caddy + API token (no Klipper)", {
    proxy: "caddy",
    extras: { apiToken: true },
  }),
  preset("compose-migrate-upstream-postgres", "Migrate from upstream Spoolman on Compose (Postgres)", {
    goal: "migrate-upstream",
    database: "postgres",
    klipper: true,
  }),
  preset("compose-switch-from-native", "Switch a native install to Docker", {
    goal: "switch",
    switchDirection: "native-to-docker",
    klipper: true,
    extras: { tz: "Europe/Stockholm" },
  }),
  preset("helm-sqlite-default", "Kubernetes (Helm), SQLite defaults", {
    platform: "helm",
  }),
  preset("helm-postgres-subpath", "Helm + Postgres, served under /spoolman (base path + probe pairing)", {
    platform: "helm",
    database: "postgres",
    subPath: "/spoolman",
  }),
  preset("helm-mysql-token", "Helm + MySQL + Ingress + API token", {
    platform: "helm",
    database: "mysql",
    proxy: "nginx",
    extras: { apiToken: true },
  }),
  preset("native-sqlite-klipper-pre20260719", "Update a pre-2026-07-19 native Klipper install", {
    goal: "update",
    platform: "native",
    klipper: true,
    installedBefore20260719: true,
  }),
  preset("native-fresh-postgres-nginx", "Fresh native install + Postgres + nginx + NFC", {
    platform: "native",
    database: "postgres",
    proxy: "nginx",
    extras: { nfc: true },
  }),
];
