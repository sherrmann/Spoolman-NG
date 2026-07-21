import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { buildCompose } from "../model/artifacts/compose";
import { buildEnv } from "../model/artifacts/env";
import { buildHelmValues } from "../model/artifacts/helmValues";
import { defaultConfig, type WizardConfig } from "../model/config";
import { buildPlan } from "../model/plan";
import { presets } from "../model/presets";
import { readRepoFile } from "./repoFiles";

function cfg(overrides: Partial<WizardConfig>): WizardConfig {
  return { ...defaultConfig, ...overrides, extras: { ...defaultConfig.extras, ...(overrides.extras ?? {}) } };
}

/** A config that exercises every optional emission at once (token without Klipper). */
const kitchenSink = cfg({
  database: "postgres",
  proxy: "nginx",
  subPath: "/spoolman",
  extras: { nfc: true, apiToken: true, tz: "Europe/Berlin", puidPgid: { puid: 99, pgid: 100 } },
});

describe("canonical repo files stay the source of truth", () => {
  it("the SQLite default compose matches the root docker-compose.yml semantically", () => {
    const canonical = parse(readRepoFile("docker-compose.yml"));
    const generated = parse(buildCompose(cfg({ extras: { ...defaultConfig.extras, tz: "Europe/Stockholm" } })));
    expect(generated.services.spoolman.image).toBe(canonical.services.spoolman.image);
    expect(generated.services.spoolman.volumes).toEqual(canonical.services.spoolman.volumes);
    expect(generated.services.spoolman.ports).toEqual(canonical.services.spoolman.ports);
    expect(generated.services.spoolman.environment).toEqual(canonical.services.spoolman.environment);
    expect(generated.services.spoolman.restart).toBe(canonical.services.spoolman.restart);
  });

  it("every SPOOLMAN_*/PUID/PGID variable the generators emit exists in .env.example", () => {
    const envExample = readRepoFile(".env.example");
    const known = new Set([...envExample.matchAll(/^#?\s*([A-Z0-9_]+)=/gm)].map((m) => m[1]));

    const emitted = new Set<string>();
    // .env generator (all branches via the kitchen sink + every preset's env artifact)
    for (const text of [
      buildEnv({ ...kitchenSink, platform: "native" }),
      ...presets.flatMap((p) =>
        buildPlan(p.config)
          .artifacts.filter((a) => a.id === "env")
          .map((a) => a.content),
      ),
    ]) {
      for (const match of text.matchAll(/^([A-Z0-9_]+)=/gm)) emitted.add(match[1]);
    }
    // compose generator environment entries
    for (const config of [kitchenSink, cfg({ database: "mysql" })]) {
      const doc = parse(buildCompose(config));
      for (const entry of doc.services.spoolman.environment as string[]) {
        emitted.add(entry.split("=")[0]);
      }
    }
    // helm values env keys
    for (const config of [
      { ...kitchenSink, platform: "helm" as const },
      cfg({ platform: "helm", database: "mysql" }),
    ]) {
      const doc = parse(buildHelmValues(config));
      for (const key of Object.keys(doc.env ?? {})) emitted.add(key);
    }

    // TZ is a generic container variable (documented in the compose examples), not a SPOOLMAN_* setting.
    emitted.delete("TZ");
    for (const name of emitted) {
      expect(known, `${name} is not documented in .env.example`).toContain(name);
    }
  });

  it("every top-level Helm values key the generator emits exists in the chart's values.yaml", () => {
    const chartKeys = new Set(Object.keys(parse(readRepoFile("charts/spoolman-ng/values.yaml"))));
    const sources = [
      buildHelmValues({ ...kitchenSink, platform: "helm" }),
      buildHelmValues(cfg({ platform: "helm", goal: "migrate-upstream", database: "postgres", proxy: "caddy" })),
      ...presets.flatMap((p) =>
        buildPlan(p.config)
          .artifacts.filter((a) => a.id === "values")
          .map((a) => a.content),
      ),
    ];
    for (const text of sources) {
      for (const key of Object.keys(parse(text) ?? {})) {
        expect(chartKeys, `values key "${key}" is not in charts/spoolman-ng/values.yaml`).toContain(key);
      }
    }
  });
});
