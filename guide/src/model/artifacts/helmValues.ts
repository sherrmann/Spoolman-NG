import type { WizardConfig } from "../config";
import { helmSubPathPairing } from "../rules";
import { HOSTNAME_PLACEHOLDER } from "../placeholders";
import type { Artifact } from "../types";

export const DB_SECRET_NAME = "spoolman-db";

/**
 * Helm values for charts/spoolman-ng. Every top-level key emitted here exists
 * in the chart's values.yaml (drift-tested). Sub-path serving always sets
 * env.SPOOLMAN_BASE_PATH and probes.path together (rule 4 — single code path).
 */
export function buildHelmValues(cfg: WizardConfig): string {
  const pairing = cfg.subPath ? helmSubPathPairing(cfg.subPath) : null;
  const lines: string[] = [
    "# Spoolman-NG Helm values. Install with:",
    "#   helm install spoolman oci://ghcr.io/sherrmann/charts/spoolman-ng -f values.yaml",
  ];

  const env: string[] = [];
  if (cfg.extras.tz) env.push(`  TZ: ${cfg.extras.tz}`);
  if (pairing) env.push(`  SPOOLMAN_BASE_PATH: ${pairing.basePath}`);
  if (cfg.database !== "sqlite") {
    env.push(`  SPOOLMAN_DB_TYPE: ${cfg.database}`);
    env.push("  SPOOLMAN_DB_HOST: my-database-host # point at your database server; the chart bundles none");
    env.push(`  SPOOLMAN_DB_PORT: "${cfg.database === "postgres" ? "5432" : "3306"}"`);
    env.push("  SPOOLMAN_DB_NAME: spoolman");
    env.push("  SPOOLMAN_DB_USERNAME: spoolman");
  }
  if (cfg.extras.apiToken) {
    env.push("  SPOOLMAN_API_TOKEN: change-me # generate one: openssl rand -hex 32");
  }

  lines.push("");
  if (env.length > 0) {
    lines.push("env:");
    lines.push(...env);
  } else {
    lines.push("# The chart defaults suit a single-node SQLite install: 1 replica, a 1 Gi PVC,");
    lines.push("# health probes on /api/v1/health, and a non-root security context.");
    lines.push("# Any SPOOLMAN_* variable from docs/installation.md can go under env:.");
    lines.push("env: {}");
  }

  if (cfg.database !== "sqlite") {
    lines.push("");
    lines.push("# Mounts the secret's key as a file (SPOOLMAN_DB_PASSWORD_FILE) — no password in values.");
    lines.push("dbPasswordSecret:");
    lines.push(`  name: ${DB_SECRET_NAME}`);
    lines.push("  key: password");
  }

  if (pairing) {
    lines.push("");
    lines.push("# Sub-path serving: the base path and the probe path must move together.");
    lines.push("probes:");
    lines.push(`  path: ${pairing.probePath}`);
  }

  if (cfg.proxy !== "none") {
    lines.push("");
    lines.push("ingress:");
    lines.push("  enabled: true");
    lines.push("  hosts:");
    lines.push(`    - host: ${HOSTNAME_PLACEHOLDER}`);
    lines.push(`      paths: [{ path: ${cfg.subPath ?? "/"}, pathType: Prefix }]`);
  }

  if (cfg.goal === "migrate-upstream") {
    lines.push("");
    lines.push("persistence:");
    lines.push("  size: 1Gi");
    lines.push("  # Reuse the PVC your previous install wrote to (or restore a backup into a fresh one):");
    lines.push("  # existingClaim: my-existing-pvc");
  }

  return `${lines.join("\n")}\n`;
}

export function helmValuesArtifact(cfg: WizardConfig): Artifact {
  return {
    id: "values",
    filename: "values.yaml",
    language: "yaml",
    title: "values.yaml (Helm)",
    content: buildHelmValues(cfg),
  };
}
