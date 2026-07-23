import { describe, expect, it } from "vitest";
import { defaultConfig, normalizeSubPath, type WizardConfig } from "./config";
import { helmSubPathPairing, normalizeConfig } from "./rules";

function cfg(overrides: Partial<WizardConfig>): WizardConfig {
  return { ...defaultConfig, ...overrides, extras: { ...defaultConfig.extras, ...(overrides.extras ?? {}) } };
}

describe("rule 1 — #268: Klipper + API token", () => {
  it("drops the token and warns", () => {
    const { effective, warnings } = normalizeConfig(
      cfg({ klipper: true, extras: { ...defaultConfig.extras, apiToken: true } }),
    );
    expect(effective.extras.apiToken).toBe(false);
    expect(warnings.map((w) => w.id)).toContain("token-dropped-for-klipper");
    expect(warnings.find((w) => w.id === "token-dropped-for-klipper")?.level).toBe("warning");
  });

  it("keeps the token without Klipper", () => {
    const { effective, warnings } = normalizeConfig(cfg({ extras: { ...defaultConfig.extras, apiToken: true } }));
    expect(effective.extras.apiToken).toBe(true);
    expect(warnings.map((w) => w.id)).not.toContain("token-dropped-for-klipper");
  });

  it("does not mutate its input", () => {
    const input = cfg({ klipper: true, extras: { ...defaultConfig.extras, apiToken: true } });
    normalizeConfig(input);
    expect(input.extras.apiToken).toBe(true);
  });
});

describe("goal switch resolves the effective platform", () => {
  it("native-to-docker targets compose", () => {
    const { effective } = normalizeConfig(
      cfg({ goal: "switch", switchDirection: "native-to-docker", platform: "helm" }),
    );
    expect(effective.platform).toBe("compose");
  });

  it("docker-to-native targets native", () => {
    const { effective } = normalizeConfig(cfg({ goal: "switch", switchDirection: "docker-to-native" }));
    expect(effective.platform).toBe("native");
  });
});

describe("sub-path normalization", () => {
  it.each([
    ["spoolman", "/spoolman"],
    ["/spoolman", "/spoolman"],
    ["/spoolman/", "/spoolman"],
    ["  /spoolman  ", "/spoolman"],
    ["", null],
    ["/", null],
  ])("%j → %j", (input, expected) => {
    expect(normalizeSubPath(input)).toBe(expected);
  });
});

describe("pre-2026-07-19 flag only applies to native Klipper updates", () => {
  it("survives for goal=update on native with Klipper", () => {
    const { effective } = normalizeConfig(
      cfg({ goal: "update", platform: "native", klipper: true, installedBefore20260719: true }),
    );
    expect(effective.installedBefore20260719).toBe(true);
  });

  it.each([
    cfg({ goal: "update", platform: "compose", klipper: true, installedBefore20260719: true }),
    cfg({ goal: "update", platform: "native", klipper: false, installedBefore20260719: true }),
    cfg({ goal: "fresh", platform: "native", klipper: true, installedBefore20260719: true }),
  ])("is cleared otherwise", (input) => {
    expect(normalizeConfig(input).effective.installedBefore20260719).toBe(false);
  });
});

describe("plan-wide warnings", () => {
  it("migrating from upstream always warns to back up first", () => {
    const { warnings } = normalizeConfig(cfg({ goal: "migrate-upstream" }));
    expect(warnings.find((w) => w.id === "backup-before-migrating")?.level).toBe("warning");
  });

  it("updating carries a backup reminder", () => {
    const { warnings } = normalizeConfig(cfg({ goal: "update" }));
    expect(warnings.map((w) => w.id)).toContain("backup-before-updating");
  });
});

describe("rule 4 — helm sub-path pairing comes from one code path", () => {
  it("derives both paths from the same input", () => {
    expect(helmSubPathPairing("/spoolman")).toEqual({
      basePath: "/spoolman",
      probePath: "/spoolman/api/v1/health",
    });
  });
});

describe("rule - #364 AI hardware gate", () => {
  it("refuses the local sidecar on 32-bit ARM and steers to a remote endpoint", () => {
    const { effective, warnings } = normalizeConfig(cfg({ ai: { choice: "local", arch: "arm32" } }));
    expect(effective.ai.choice).toBe("remote");
    expect(warnings.map((w) => w.id)).toContain("ai-sidecar-refused-armv7");
  });

  it("keeps the sidecar on 64-bit hardware without a warning", () => {
    const { effective, warnings } = normalizeConfig(cfg({ ai: { choice: "local", arch: "arm64" } }));
    expect(effective.ai.choice).toBe("local");
    expect(warnings.map((w) => w.id)).not.toContain("ai-sidecar-refused-armv7");
  });

  it("forces AI to none where the wizard does not control the runtime", () => {
    const helm = normalizeConfig(cfg({ platform: "helm", ai: { choice: "local", arch: "amd64" } }));
    expect(helm.effective.ai.choice).toBe("none");
    const update = normalizeConfig(cfg({ goal: "update", ai: { choice: "local", arch: "amd64" } }));
    expect(update.effective.ai.choice).toBe("none");
  });
});
