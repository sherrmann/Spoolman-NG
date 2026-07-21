import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { defaultConfig, type WizardConfig } from "./config";
import { buildPlan } from "./plan";
import { presets } from "./presets";

function cfg(overrides: Partial<WizardConfig>): WizardConfig {
  return { ...defaultConfig, ...overrides, extras: { ...defaultConfig.extras, ...(overrides.extras ?? {}) } };
}

function stepIds(config: WizardConfig): string[] {
  return buildPlan(config).steps.map((s) => s.id);
}

function artifactIds(config: WizardConfig): string[] {
  return buildPlan(config).artifacts.map((a) => a.id);
}

describe("step assembly per goal × platform", () => {
  it("fresh compose: file → start", () => {
    expect(stepIds(cfg({}))).toEqual(["compose-file", "start"]);
  });

  it("fresh compose with Caddy adds a proxy step", () => {
    expect(stepIds(cfg({ proxy: "caddy" }))).toEqual(["compose-file", "start", "proxy"]);
  });

  it("rule 2 — Klipper adds the tracking step on every platform", () => {
    for (const platform of ["compose", "native", "helm", "ha-addon", "third-party-chart"] as const) {
      const plan = buildPlan(cfg({ platform, klipper: true }));
      expect(plan.steps.map((s) => s.id)).toContain("klipper-tracking");
      expect(plan.artifacts.map((a) => a.id)).toContain("moonraker-spoolman");
    }
  });

  it("rule 3 — the update_manager recipe is native-only", () => {
    expect(artifactIds(cfg({ platform: "native", klipper: true }))).toContain("moonraker-update-manager");
    expect(stepIds(cfg({ platform: "native", klipper: true }))).toContain("klipper-updater");
    for (const platform of ["compose", "helm", "ha-addon", "third-party-chart"] as const) {
      expect(artifactIds(cfg({ platform, klipper: true }))).not.toContain("moonraker-update-manager");
      expect(stepIds(cfg({ platform, klipper: true }))).not.toContain("klipper-updater");
    }
  });

  it("rule 12 — the release_info fix leads the update flow only when flagged", () => {
    const flagged = cfg({ goal: "update", platform: "native", klipper: true, installedBefore20260719: true });
    expect(stepIds(flagged)[0]).toBe("release-info-fix");
    const unflagged = cfg({ goal: "update", platform: "native", klipper: true });
    expect(stepIds(unflagged)).not.toContain("release-info-fix");
  });

  it("rule 21 — native Klipper updates lead with the printer UI and keep the shell fallback", () => {
    const ids = stepIds(cfg({ goal: "update", platform: "native", klipper: true }));
    expect(ids.indexOf("update-from-printer-ui")).toBeLessThan(ids.indexOf("update-native"));
  });

  it("rule 13 — migrating on compose is stop → swap image → start, with no full compose artifact", () => {
    const plan = buildPlan(cfg({ goal: "migrate-upstream" }));
    expect(plan.steps.map((s) => s.id)).toEqual(["migrate-stop", "migrate-swap-image", "migrate-start"]);
    expect(plan.artifacts).toEqual([]);
    expect(plan.warnings.map((w) => w.id)).toContain("backup-before-migrating");
    expect(plan.steps[1].code?.content).toContain("ghcr.io/sherrmann/spoolman-ng:latest");
  });

  it("rule 16 — switching covers both directions with data-copy steps", () => {
    const toDocker = stepIds(cfg({ goal: "switch", switchDirection: "native-to-docker" }));
    expect(toDocker).toEqual(["switch-stop-native", "compose-file", "switch-copy-data", "start", "switch-cleanup"]);
    const toNative = stepIds(cfg({ goal: "switch", switchDirection: "docker-to-native" }));
    expect(toNative).toEqual(["switch-stop-docker", "install", "configure-env", "switch-copy-data"]);
  });

  it("rule 14 — the HA add-on flow links out and emits no file artifacts", () => {
    const plan = buildPlan(cfg({ platform: "ha-addon", klipper: true }));
    expect(plan.steps[0].body).toContain("spoolman-ng-addons");
    expect(plan.artifacts.map((a) => a.id)).toEqual(["moonraker-spoolman"]);
  });

  it("rule 15 — third-party charts get the image override and the sub-path pairing note", () => {
    const plan = buildPlan(cfg({ platform: "third-party-chart", subPath: "/spoolman" }));
    const override = plan.steps.find((s) => s.id === "chart-override");
    expect(override?.code?.content).toContain("ghcr.io/sherrmann/spoolman-ng");
    const subPath = plan.steps.find((s) => s.id === "chart-subpath");
    expect(subPath?.body).toContain("SPOOLMAN_BASE_PATH");
    expect(subPath?.body).toContain("/spoolman/api/v1/health");
  });

  it("rule 20 — the armv7 note rides the install/start step on compose and native", () => {
    const compose = buildPlan(cfg({}));
    expect(compose.steps.find((s) => s.id === "start")?.notes?.map((n) => n.id)).toContain("armv7-best-effort");
    const native = buildPlan(cfg({ platform: "native" }));
    expect(native.steps.find((s) => s.id === "install")?.notes?.map((n) => n.id)).toContain("armv7-best-effort");
  });

  it("rule 11 — NFC brings the HTTPS note everywhere and uv sync on native", () => {
    const native = buildPlan(cfg({ platform: "native", extras: { ...defaultConfig.extras, nfc: true } }));
    const nfcStep = native.steps.find((s) => s.id === "nfc");
    expect(nfcStep?.commands?.join(" ")).toContain("uv sync --extra nfc");
    expect(nfcStep?.notes?.map((n) => n.id)).toContain("nfc-needs-https");
    const helm = buildPlan(cfg({ platform: "helm", extras: { ...defaultConfig.extras, nfc: true } }));
    expect(helm.steps.find((s) => s.id === "nfc")?.notes?.map((n) => n.id)).toContain("nfc-needs-https");
  });

  it("rule 6 — proxy steps carry the WebSocket note, and Klipper adds the proxy-auth warning", () => {
    const plan = buildPlan(cfg({ proxy: "nginx", klipper: true }));
    const proxy = plan.steps.find((s) => s.id === "proxy");
    expect(proxy?.notes?.map((n) => n.id)).toEqual(expect.arrayContaining(["proxy-websockets", "proxy-auth-klipper"]));
  });

  it("rule 5 — caddy/nginx with a sub-path gets guidance instead of an untested snippet", () => {
    const plan = buildPlan(cfg({ proxy: "nginx", subPath: "/spoolman" }));
    expect(plan.artifacts.map((a) => a.id)).not.toContain("proxy-nginx");
    expect(plan.steps.find((s) => s.id === "proxy")?.body).toContain("SPOOLMAN_BASE_PATH=/spoolman");
  });

  it("rule 8 — helm with an external database leads with the secret step", () => {
    const ids = stepIds(cfg({ platform: "helm", database: "postgres" }));
    expect(ids[0]).toBe("db-secret");
  });
});

describe("plan invariants across every preset", () => {
  it("every referenced artifact exists and every artifact is referenced", () => {
    for (const preset of presets) {
      const plan = buildPlan(preset.config);
      const artifactIds = new Set(plan.artifacts.map((a) => a.id));
      const referenced = new Set(plan.steps.flatMap((s) => s.artifactIds ?? []));
      for (const id of referenced) expect(artifactIds, `${preset.id}: step references ${id}`).toContain(id);
      for (const id of artifactIds) expect(referenced, `${preset.id}: artifact ${id} is orphaned`).toContain(id);
    }
  });

  it("artifact ids and step ids are unique within a plan", () => {
    for (const preset of presets) {
      const plan = buildPlan(preset.config);
      const aIds = plan.artifacts.map((a) => a.id);
      const sIds = plan.steps.map((s) => s.id);
      expect(new Set(aIds).size, preset.id).toBe(aIds.length);
      expect(new Set(sIds).size, preset.id).toBe(sIds.length);
    }
  });

  it("every YAML artifact parses", () => {
    for (const preset of presets) {
      for (const artifact of buildPlan(preset.config).artifacts) {
        if (artifact.language === "yaml") {
          expect(() => parse(artifact.content), `${preset.id}/${artifact.id}`).not.toThrow();
        }
      }
    }
  });

  it("no artifact ever leaks an unresolved {{placeholder}}", () => {
    for (const preset of presets) {
      for (const artifact of buildPlan(preset.config).artifacts) {
        expect(artifact.content, `${preset.id}/${artifact.id}`).not.toMatch(/\{\{[A-Z0-9_]+\}\}/);
      }
    }
  });
});
