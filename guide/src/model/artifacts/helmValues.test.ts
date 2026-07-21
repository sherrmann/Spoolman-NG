import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { defaultConfig, type WizardConfig } from "../config";
import { presets } from "../presets";
import { buildPlan } from "../plan";
import { buildHelmValues } from "./helmValues";

function cfg(overrides: Partial<WizardConfig>): WizardConfig {
  return {
    ...defaultConfig,
    platform: "helm",
    ...overrides,
    extras: { ...defaultConfig.extras, ...(overrides.extras ?? {}) },
  };
}

describe("helm values generator", () => {
  it("SQLite default renders an empty env map and nothing surprising", () => {
    const doc = parse(buildHelmValues(cfg({})));
    expect(doc).toEqual({ env: {} });
  });

  it("rule 4 — a sub-path always sets base path, probe path and (with ingress) the ingress path together", () => {
    const doc = parse(buildHelmValues(cfg({ subPath: "/spoolman", proxy: "nginx" })));
    expect(doc.env.SPOOLMAN_BASE_PATH).toBe("/spoolman");
    expect(doc.probes.path).toBe("/spoolman/api/v1/health");
    expect(doc.ingress.hosts[0].paths).toEqual([{ path: "/spoolman", pathType: "Prefix" }]);
  });

  it("rule 4 property — across every preset, base path and probe path only ever appear together", () => {
    for (const preset of presets) {
      const values = buildPlan(preset.config).artifacts.find((a) => a.id === "values");
      if (!values) continue;
      const doc = parse(values.content);
      const basePath: string | undefined = doc?.env?.SPOOLMAN_BASE_PATH;
      const probePath: string | undefined = doc?.probes?.path;
      expect(basePath === undefined).toBe(probePath === undefined);
      if (basePath !== undefined) expect(probePath).toBe(`${basePath}/api/v1/health`);
    }
  });

  it("rule 8 — external databases mount the password from a Secret, never inline", () => {
    const doc = parse(buildHelmValues(cfg({ database: "postgres" })));
    expect(doc.env.SPOOLMAN_DB_TYPE).toBe("postgres");
    expect(doc.env.SPOOLMAN_DB_PORT).toBe("5432");
    expect(doc.env.SPOOLMAN_DB_USERNAME).toBe("spoolman");
    expect(doc.env.SPOOLMAN_DB_PASSWORD).toBeUndefined();
    expect(doc.dbPasswordSecret).toEqual({ name: "spoolman-db", key: "password" });
  });

  it("ingress appears only when asked for", () => {
    expect(parse(buildHelmValues(cfg({}))).ingress).toBeUndefined();
    const doc = parse(buildHelmValues(cfg({ proxy: "caddy" })));
    expect(doc.ingress.enabled).toBe(true);
    expect(doc.ingress.hosts[0].host).toBe("spoolman.example.com");
  });

  it("rule 19 — token lands under env when Klipper is not in play", () => {
    const doc = parse(buildHelmValues(cfg({ extras: { ...defaultConfig.extras, apiToken: true } })));
    expect(doc.env.SPOOLMAN_API_TOKEN).toBe("change-me");
  });

  it("rule 18 — TZ lands under env", () => {
    const doc = parse(buildHelmValues(cfg({ extras: { ...defaultConfig.extras, tz: "Europe/Berlin" } })));
    expect(doc.env.TZ).toBe("Europe/Berlin");
  });

  it("migrating keeps a persistence block with the existingClaim escape hatch in comments", () => {
    const text = buildHelmValues(cfg({ goal: "migrate-upstream" }));
    expect(parse(text).persistence).toEqual({ size: "1Gi" });
    expect(text).toContain("# existingClaim:");
  });
});
