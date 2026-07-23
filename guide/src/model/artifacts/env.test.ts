import { describe, expect, it } from "vitest";
import { defaultConfig, type WizardConfig } from "../config";
import { buildEnv } from "./env";

function cfg(overrides: Partial<WizardConfig>): WizardConfig {
  return {
    ...defaultConfig,
    platform: "native",
    ...overrides,
    extras: { ...defaultConfig.extras, ...(overrides.extras ?? {}) },
  };
}

function assignments(text: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const match = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (match) result[match[1]] = match[2];
  }
  return result;
}

describe(".env generator (native)", () => {
  it("SQLite default sets only host and port", () => {
    expect(assignments(buildEnv(cfg({})))).toEqual({ SPOOLMAN_HOST: "0.0.0.0", SPOOLMAN_PORT: "7912" });
  });

  it("rule 9 — external database block points at an existing server", () => {
    const vars = assignments(buildEnv(cfg({ database: "mysql" })));
    expect(vars.SPOOLMAN_DB_TYPE).toBe("mysql");
    expect(vars.SPOOLMAN_DB_PORT).toBe("3306");
    expect(vars.SPOOLMAN_DB_PASSWORD).toBe("change-me");
  });

  it("rule 5 — a sub-path sets SPOOLMAN_BASE_PATH", () => {
    expect(assignments(buildEnv(cfg({ subPath: "/spoolman" }))).SPOOLMAN_BASE_PATH).toBe("/spoolman");
  });

  it("rules 11/19 — NFC and API token blocks", () => {
    const vars = assignments(buildEnv(cfg({ extras: { ...defaultConfig.extras, nfc: true, apiToken: true } })));
    expect(vars.SPOOLMAN_NFC_ENABLED).toBe("TRUE");
    expect(vars.SPOOLMAN_API_TOKEN).toBe("change-me");
  });

  it("migrating from upstream explains the drop-in data directory", () => {
    expect(buildEnv(cfg({ goal: "migrate-upstream" }))).toContain("drop-in replacement");
  });
});

describe("AI endpoint prefill (#364)", () => {
  it("points SPOOLMAN_AI_BASE_URL at the local Ollama for the local choice", () => {
    const vars = assignments(buildEnv(cfg({ ai: { choice: "local", arch: "arm64" } })));
    expect(vars.SPOOLMAN_AI_BASE_URL).toBe("http://localhost:11434/v1");
  });

  it("emits nothing AI-related for remote and none choices", () => {
    for (const choice of ["remote", "none"] as const) {
      const vars = assignments(buildEnv(cfg({ ai: { choice, arch: "amd64" } })));
      expect(vars.SPOOLMAN_AI_BASE_URL).toBeUndefined();
    }
  });
});
