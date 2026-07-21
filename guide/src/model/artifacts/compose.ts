import type { WizardConfig } from "../config";
import { DB_PASSWORD_PLACEHOLDER, API_TOKEN_PLACEHOLDER, HOSTNAME_PLACEHOLDER } from "../placeholders";
import type { Artifact } from "../types";

function dbServiceLines(database: "postgres" | "mysql"): string[] {
  if (database === "postgres") {
    return [
      "  db:",
      "    image: postgres:16-alpine",
      "    restart: unless-stopped",
      "    environment:",
      "      - POSTGRES_DB=spoolman",
      "      - POSTGRES_USER=spoolman",
      `      - POSTGRES_PASSWORD=${DB_PASSWORD_PLACEHOLDER} # must match SPOOLMAN_DB_PASSWORD above`,
      "    volumes:",
      "      - db-data:/var/lib/postgresql/data",
      "    healthcheck:",
      '      test: ["CMD-SHELL", "pg_isready -U spoolman -d spoolman"]',
      "      interval: 5s",
      "      timeout: 5s",
      "      retries: 12",
    ];
  }
  return [
    "  db:",
    "    image: mariadb:lts",
    "    restart: unless-stopped",
    "    environment:",
    "      - MARIADB_DATABASE=spoolman",
    "      - MARIADB_USER=spoolman",
    `      - MARIADB_PASSWORD=${DB_PASSWORD_PLACEHOLDER} # must match SPOOLMAN_DB_PASSWORD above`,
    "      - MARIADB_RANDOM_ROOT_PASSWORD=yes",
    "    volumes:",
    "      - db-data:/var/lib/mysql",
    "    healthcheck:",
    '      test: ["CMD", "/usr/local/bin/healthcheck.sh", "--su-mysql", "--connect", "--innodb_initialized"]',
    "      interval: 5s",
    "      timeout: 5s",
    "      retries: 12",
  ];
}

/**
 * Assembles a docker-compose.yml. The SQLite/no-extras output intentionally
 * matches the canonical root docker-compose.yml (drift-tested semantically).
 */
export function buildCompose(cfg: WizardConfig): string {
  const externalDb = cfg.database !== "sqlite";
  const lines: string[] = [
    "services:",
    "  spoolman:",
    "    image: ghcr.io/sherrmann/spoolman-ng:latest # Also on Docker Hub: cookiemonster95/spoolman-ng:latest",
    "    restart: unless-stopped",
    "    volumes:",
    "      # Keeps your database outside the container lifecycle. Do NOT modify the target path.",
    "      - ./data:/home/app/.local/share/spoolman",
    "    ports:",
    '      - "7912:8000"',
  ];

  const env: string[] = [];
  if (cfg.extras.tz) env.push(`TZ=${cfg.extras.tz} # timezone, used for timestamps in the UI/API`);
  if (cfg.extras.puidPgid) {
    env.push(`PUID=${cfg.extras.puidPgid.puid} # user id that owns the data volume`);
    env.push(`PGID=${cfg.extras.puidPgid.pgid} # group id that owns the data volume`);
  }
  if (cfg.subPath) env.push(`SPOOLMAN_BASE_PATH=${cfg.subPath}`);
  if (externalDb) {
    env.push(`SPOOLMAN_DB_TYPE=${cfg.database}`);
    env.push("SPOOLMAN_DB_HOST=db");
    env.push(`SPOOLMAN_DB_PORT=${cfg.database === "postgres" ? "5432" : "3306"}`);
    env.push("SPOOLMAN_DB_NAME=spoolman");
    env.push("SPOOLMAN_DB_USERNAME=spoolman");
    env.push(`SPOOLMAN_DB_PASSWORD=${DB_PASSWORD_PLACEHOLDER}`);
  }
  if (cfg.extras.apiToken) {
    env.push(`SPOOLMAN_API_TOKEN=${API_TOKEN_PLACEHOLDER} # generate one: openssl rand -hex 32`);
  }
  if (cfg.extras.nfc) env.push("SPOOLMAN_NFC_ENABLED=TRUE # server-side USB NFC reader — see docs/nfc.md");
  if (env.length > 0) {
    lines.push("    environment:");
    for (const entry of env) lines.push(`      - ${entry}`);
  }

  if (cfg.extras.nfc) {
    lines.push("    devices:");
    lines.push("      # Pass the USB NFC reader through to the container (see docs/nfc.md).");
    lines.push("      - /dev/bus/usb:/dev/bus/usb");
  }

  if (cfg.proxy === "traefik") {
    lines.push("    labels:");
    lines.push("      - traefik.enable=true");
    lines.push(
      cfg.subPath
        ? `      - traefik.http.routers.spoolman.rule=PathPrefix(\`${cfg.subPath}\`)`
        : `      - traefik.http.routers.spoolman.rule=Host(\`${HOSTNAME_PLACEHOLDER}\`)`,
    );
    lines.push("      - traefik.http.services.spoolman.loadbalancer.server.port=8000");
  }

  if (externalDb) {
    lines.push("    depends_on:");
    lines.push("      db:");
    lines.push("        condition: service_healthy");
    lines.push("");
    lines.push(...dbServiceLines(cfg.database as "postgres" | "mysql"));
    lines.push("");
    lines.push("volumes:");
    lines.push("  db-data:");
  }

  return `${lines.join("\n")}\n`;
}

export function composeArtifact(cfg: WizardConfig): Artifact {
  return {
    id: "compose",
    filename: "docker-compose.yml",
    language: "yaml",
    title: "docker-compose.yml",
    content: buildCompose(cfg),
  };
}
