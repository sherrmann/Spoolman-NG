import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { defaultConfig, type WizardConfig } from "../config";
import { buildPlan } from "../plan";
import { buildCompose } from "./compose";

function cfg(overrides: Partial<WizardConfig>): WizardConfig {
  return { ...defaultConfig, ...overrides, extras: { ...defaultConfig.extras, ...(overrides.extras ?? {}) } };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function parsed(config: WizardConfig): any {
  return parse(buildCompose(config));
}

describe("compose generator", () => {
  it("SQLite default: single service, canonical image/volume/port", () => {
    const doc = parsed(cfg({ extras: { ...defaultConfig.extras, tz: "Europe/Stockholm" } }));
    expect(Object.keys(doc.services)).toEqual(["spoolman"]);
    expect(doc.volumes).toBeUndefined();
    const svc = doc.services.spoolman;
    expect(svc.image).toBe("ghcr.io/sherrmann/spoolman-ng:latest");
    expect(svc.volumes).toEqual(["./data:/home/app/.local/share/spoolman"]);
    expect(svc.ports).toEqual(["7912:8000"]);
    expect(svc.environment).toEqual(["TZ=Europe/Stockholm"]);
  });

  it.each([
    ["postgres", "postgres:16-alpine", "5432", "/var/lib/postgresql/data"],
    ["mysql", "mariadb:lts", "3306", "/var/lib/mysql"],
  ] as const)("rule 7 — %s gets a healthy sidecar and full SPOOLMAN_DB_* wiring", (db, image, port, dataDir) => {
    const doc = parsed(cfg({ database: db }));
    expect(doc.services.db.image).toBe(image);
    expect(doc.services.db.healthcheck.test[0]).toMatch(/CMD/);
    expect(doc.services.db.volumes).toEqual([`db-data:${dataDir}`]);
    expect(doc.services.spoolman.depends_on).toEqual({ db: { condition: "service_healthy" } });
    expect(doc.volumes).toEqual({ "db-data": null });
    const env: string[] = doc.services.spoolman.environment;
    expect(env).toContain(`SPOOLMAN_DB_TYPE=${db}`);
    expect(env).toContain("SPOOLMAN_DB_HOST=db");
    expect(env).toContain(`SPOOLMAN_DB_PORT=${port}`);
    expect(env).toContain("SPOOLMAN_DB_NAME=spoolman");
    expect(env).toContain("SPOOLMAN_DB_USERNAME=spoolman");
    expect(env).toContain("SPOOLMAN_DB_PASSWORD=change-me");
  });

  it("the change-me password appears on both sides so they can be changed together", () => {
    const text = buildCompose(cfg({ database: "postgres" }));
    expect(text.match(/change-me/g)).toHaveLength(2);
  });

  it("rule 5/6 — traefik with a sub-path pairs PathPrefix with SPOOLMAN_BASE_PATH", () => {
    const doc = parsed(cfg({ proxy: "traefik", subPath: "/spoolman" }));
    expect(doc.services.spoolman.labels).toEqual([
      "traefik.enable=true",
      "traefik.http.routers.spoolman.rule=PathPrefix(`/spoolman`)",
      "traefik.http.services.spoolman.loadbalancer.server.port=8000",
    ]);
    expect(doc.services.spoolman.environment).toContain("SPOOLMAN_BASE_PATH=/spoolman");
  });

  it("traefik without a sub-path routes by hostname and sets no base path", () => {
    const doc = parsed(cfg({ proxy: "traefik" }));
    expect(doc.services.spoolman.labels).toContain("traefik.http.routers.spoolman.rule=Host(`spoolman.example.com`)");
    expect(doc.services.spoolman.environment ?? []).not.toContain("SPOOLMAN_BASE_PATH=/spoolman");
  });

  it("rule 10 — NFC passes the USB bus through and enables the reader", () => {
    const doc = parsed(cfg({ extras: { ...defaultConfig.extras, nfc: true } }));
    expect(doc.services.spoolman.devices).toEqual(["/dev/bus/usb:/dev/bus/usb"]);
    expect(doc.services.spoolman.environment).toContain("SPOOLMAN_NFC_ENABLED=TRUE");
  });

  it("rule 17/18 — PUID/PGID and TZ land as env entries", () => {
    const doc = parsed(
      cfg({ extras: { ...defaultConfig.extras, tz: "Europe/Berlin", puidPgid: { puid: 99, pgid: 100 } } }),
    );
    const env: string[] = doc.services.spoolman.environment;
    expect(env).toContain("TZ=Europe/Berlin");
    expect(env).toContain("PUID=99");
    expect(env).toContain("PGID=100");
  });

  it("rule 19 — the API token is included when Klipper is not in play", () => {
    const doc = parsed(cfg({ extras: { ...defaultConfig.extras, apiToken: true } }));
    expect(doc.services.spoolman.environment).toContain("SPOOLMAN_API_TOKEN=change-me");
  });

  it("rule 1 end-to-end — Klipper + token leaves the token out of every artifact", () => {
    const plan = buildPlan(cfg({ klipper: true, extras: { ...defaultConfig.extras, apiToken: true } }));
    for (const artifact of plan.artifacts) {
      expect(artifact.content).not.toContain("SPOOLMAN_API_TOKEN");
    }
    expect(plan.warnings.map((w) => w.id)).toContain("token-dropped-for-klipper");
  });
});

describe("AI sidecar (#364)", () => {
  it("emits an ollama service, a models volume, and the base-URL wiring", () => {
    const doc = parsed(cfg({ ai: { choice: "local", arch: "amd64" } }));
    expect(Object.keys(doc.services)).toEqual(["spoolman", "ollama"]);
    expect(doc.services.ollama.image).toBe("ollama/ollama:latest");
    // Deliberately not published on the host: only Spoolman reaches it.
    expect(doc.services.ollama.ports).toBeUndefined();
    expect(doc.services.ollama.volumes).toEqual(["ollama-models:/root/.ollama"]);
    expect(doc.volumes).toEqual({ "ollama-models": null });
    const env: string[] = doc.services.spoolman.environment;
    expect(env.some((entry) => entry.startsWith("SPOOLMAN_AI_BASE_URL=http://ollama:11434/v1"))).toBe(true);
  });

  it("combines with a database sidecar - both named volumes are declared", () => {
    const doc = parsed(cfg({ database: "postgres", ai: { choice: "local", arch: "amd64" } }));
    expect(Object.keys(doc.services)).toEqual(["spoolman", "db", "ollama"]);
    expect(doc.volumes).toEqual({ "db-data": null, "ollama-models": null });
  });

  it("remote choice leaves the compose file untouched", () => {
    const doc = parsed(cfg({ ai: { choice: "remote", arch: "amd64" } }));
    expect(Object.keys(doc.services)).toEqual(["spoolman"]);
    expect(doc.services.spoolman.environment).toBeUndefined();
  });
});
