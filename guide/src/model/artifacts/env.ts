import type { WizardConfig } from "../config";
import { DB_PASSWORD_PLACEHOLDER, API_TOKEN_PLACEHOLDER } from "../placeholders";
import type { Artifact } from "../types";

/**
 * A .env for the native install. Only variables whose names exist in the
 * canonical .env.example are ever emitted (drift-tested).
 */
export function buildEnv(cfg: WizardConfig): string {
  const lines: string[] = [
    "# Spoolman-NG configuration (native install).",
    '# Full reference: .env.example and docs/installation.md → "Environment variable reference".',
    "",
    "# Interface and port the server listens on (the installer's default port is 7912).",
    "SPOOLMAN_HOST=0.0.0.0",
    "SPOOLMAN_PORT=7912",
  ];

  if (cfg.goal === "migrate-upstream") {
    lines.push(
      "",
      "# Migrating from original Spoolman: your existing data directory",
      "# (~/.local/share/spoolman) is picked up automatically — Spoolman-NG is a",
      "# drop-in replacement. Re-apply any custom settings from your old .env here.",
    );
  }

  if (cfg.subPath) {
    lines.push("", `# Serve under a sub-path (myhost.com${cfg.subPath}).`, `SPOOLMAN_BASE_PATH=${cfg.subPath}`);
  }

  if (cfg.database !== "sqlite") {
    lines.push(
      "",
      `# External ${cfg.database === "postgres" ? "PostgreSQL" : "MySQL/MariaDB"} database. Point these at your`,
      "# existing server — the installer does not provision one.",
      `SPOOLMAN_DB_TYPE=${cfg.database}`,
      "SPOOLMAN_DB_HOST=localhost",
      `SPOOLMAN_DB_PORT=${cfg.database === "postgres" ? "5432" : "3306"}`,
      "SPOOLMAN_DB_NAME=spoolman",
      "SPOOLMAN_DB_USERNAME=spoolman",
      `SPOOLMAN_DB_PASSWORD=${DB_PASSWORD_PLACEHOLDER}`,
    );
  }

  if (cfg.extras.apiToken) {
    lines.push(
      "",
      "# Require `Authorization: Bearer <token>` on all /api/v1 requests.",
      "# Generate one: openssl rand -hex 32",
      `SPOOLMAN_API_TOKEN=${API_TOKEN_PLACEHOLDER}`,
    );
  }

  if (cfg.extras.nfc) {
    lines.push(
      "",
      "# Server-side USB NFC reader — see docs/nfc.md for hardware, udev rules and",
      "# the browser (Web NFC) alternative. Also run: uv sync --extra nfc",
      "SPOOLMAN_NFC_ENABLED=TRUE",
    );
  }

  return `${lines.join("\n")}\n`;
}

export function envArtifact(cfg: WizardConfig): Artifact {
  return {
    id: "env",
    filename: ".env",
    language: "dotenv",
    title: ".env (in ~/Spoolman)",
    content: buildEnv(cfg),
  };
}
