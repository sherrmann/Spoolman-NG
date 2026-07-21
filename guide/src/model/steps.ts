import type { WizardConfig } from "./config";
import { renderFragment } from "./fragments";
import { DB_SECRET_NAME } from "./artifacts/helmValues";
import { DB_PASSWORD_PLACEHOLDER } from "./placeholders";
import type { Artifact, Note, Step } from "./types";

const ADDON_REPO_URL = "https://github.com/sherrmann/spoolman-ng-addons";
const DOCS_URL = "https://github.com/sherrmann/Spoolman-NG/blob/master/docs/installation.md";
const NFC_DOCS_URL = "https://github.com/sherrmann/Spoolman-NG/blob/master/docs/nfc.md";

const armv7Note: Note = {
  level: "info",
  id: "armv7-best-effort",
  text: "On 32-bit ARM (armv7, e.g. older Raspberry Pi OS) support is best-effort — amd64 and arm64 are the recommended targets. A 64-bit OS is worth it on Pi 3B+/4 hardware.",
};

const websocketNote: Note = {
  level: "info",
  id: "proxy-websockets",
  text: "Live updates (and Moonraker's connection) run over WebSockets under /api/v1/… — a proxy without upgrade handling serves the UI fine while live updates silently die.",
};

const proxyAuthKlipperNote: Note = {
  level: "warning",
  id: "proxy-auth-klipper",
  text: "If you add SSO/forward-auth at the proxy, keep an unauthenticated path for printer traffic — Klipper talks to Spoolman through Moonraker, which cannot authenticate.",
};

const stopBothSidesNote: Note = {
  level: "warning",
  id: "stop-both-sides",
  text: "Stop Spoolman on both sides before copying, and copy the whole directory (database plus backups/). If you use a custom SPOOLMAN_DIR_DATA, copy that directory instead.",
};

const spoolmanUrlUnchangedNote: Note = {
  level: "info",
  id: "spoolman-url-unchanged",
  text: "Your printers' [spoolman] sections keep working unchanged — the server stays on port 7912.",
};

function nfcHttpsNote(cfg: WizardConfig): Note {
  const caddyHint = cfg.proxy === "none" ? " Caddy is the least-effort way to get a trusted certificate." : "";
  return {
    level: "info",
    id: "nfc-needs-https",
    text: `Scanning NFC tags in the browser (Web NFC, Chrome on Android) requires HTTPS — put Spoolman behind a TLS-terminating proxy.${caddyHint} Server-side USB readers work without it (${NFC_DOCS_URL}).`,
  };
}

function fragmentCommands(name: string, vars?: Record<string, string>): string[] {
  return renderFragment(name, vars).trimEnd().split("\n");
}

function klipperTrackingStep(cfg: WizardConfig): Step {
  const urlHint =
    cfg.platform === "ha-addon"
      ? "Use your Home Assistant host and the port you exposed in the add-on configuration as the server URL."
      : cfg.platform === "helm"
        ? "Use the URL your Ingress (or Service) exposes as the server URL."
        : "Replace <spoolman-host> with the machine running Spoolman.";
  return {
    id: "klipper-tracking",
    title: "Wire your printer(s) into filament tracking",
    body:
      `Each printer is a client of the one shared Spoolman server — add this to every printer's moonraker.conf, then restart Moonraker. ${urlHint} ` +
      "This is not the same as [update_manager Spoolman]: that only auto-updates the software, this is what reports filament use.",
    artifactIds: ["moonraker-spoolman"],
  };
}

function klipperUpdaterStep(): Step {
  return {
    id: "klipper-updater",
    title: "One-click updates from your printer UI",
    body:
      "Two parts. First allow Moonraker to restart the service, then add the update recipe to moonraker.conf (adjust path if you installed elsewhere) and restart Moonraker. " +
      "Spoolman-NG then appears in Mainsail/Fluidd's update list. Do not use type: web — it deletes the virtualenv on update.",
    commands: ['echo "Spoolman" >> ~/printer_data/moonraker.asvc', "sudo systemctl restart moonraker"],
    artifactIds: ["moonraker-update-manager"],
    notes: [
      {
        level: "info",
        id: "updater-needs-recent-zip",
        text: "The recipe needs a release that ships requirements.txt at the zip root (releases after 2026-07-19). On an older install, re-run the install one-liner once (with unzip -o) before adding the stanza.",
      },
    ],
  };
}

function proxySteps(cfg: WizardConfig): Step[] {
  if (cfg.proxy === "none" && !cfg.subPath) return [];
  const steps: Step[] = [];
  const notes: Note[] = [websocketNote];
  if (cfg.klipper) notes.push(proxyAuthKlipperNote);

  if (cfg.proxy === "caddy" && !cfg.subPath) {
    steps.push({
      id: "proxy",
      title: "Put it behind Caddy",
      body: "Caddy fetches certificates automatically and proxies WebSockets out of the box.",
      artifactIds: ["proxy-caddy"],
      notes,
    });
  } else if (cfg.proxy === "nginx" && !cfg.subPath) {
    steps.push({
      id: "proxy",
      title: "Put it behind nginx",
      body: "Add this inside your server { } block — the Upgrade/Connection headers are the part people miss.",
      artifactIds: ["proxy-nginx"],
      notes,
    });
  } else if (cfg.proxy === "traefik") {
    steps.push({
      id: "proxy",
      title: "Traefik routing",
      body:
        "The Traefik labels are already on the spoolman service in your compose file. Traefik proxies WebSockets natively — no extra config." +
        (cfg.subPath ? ` SPOOLMAN_BASE_PATH=${cfg.subPath} is set to match the PathPrefix rule.` : ""),
      notes: cfg.klipper ? [proxyAuthKlipperNote] : undefined,
    });
  } else if (cfg.subPath) {
    steps.push({
      id: "proxy",
      title: `Serve it under ${cfg.subPath}`,
      body:
        `SPOOLMAN_BASE_PATH=${cfg.subPath} is already set in your config — the client, PWA manifest and service worker are all base-path aware. ` +
        `In your ${cfg.proxy === "none" ? "proxy" : cfg.proxy}, route the ${cfg.subPath} prefix to port 7912 and preserve WebSocket upgrades (see the Reverse proxies section of the installation guide: ${DOCS_URL}).`,
      notes,
    });
  }
  return steps;
}

function nfcSteps(cfg: WizardConfig): Step[] {
  if (!cfg.extras.nfc) return [];
  if (cfg.platform === "native") {
    return [
      {
        id: "nfc",
        title: "Enable the USB NFC reader",
        body: `The native install omits the NFC extra by default. For reader hardware, udev rules and the SPOOLMAN_NFC_* variables, see ${NFC_DOCS_URL}.`,
        commands: ["cd ~/Spoolman && uv sync --extra nfc"],
        notes: [nfcHttpsNote(cfg)],
      },
    ];
  }
  return [
    {
      id: "nfc",
      title: "NFC notes",
      body:
        cfg.platform === "compose"
          ? `The USB reader pass-through (devices:) and SPOOLMAN_NFC_ENABLED are already in your compose file. Hardware, udev rules and reader options: ${NFC_DOCS_URL}.`
          : `Server-side USB readers need the device passed into the container — straightforward with Docker, cluster-specific on Kubernetes. See ${NFC_DOCS_URL}.`,
      notes: [nfcHttpsNote(cfg)],
    },
  ];
}

function freshSteps(cfg: WizardConfig): Step[] {
  const steps: Step[] = [];
  switch (cfg.platform) {
    case "compose": {
      const composeNotes: Note[] = [];
      if (cfg.database !== "sqlite") {
        composeNotes.push({
          level: "warning",
          id: "change-db-password",
          text: `Change the ${DB_PASSWORD_PLACEHOLDER} database password — it appears twice (SPOOLMAN_DB_PASSWORD and the db service) and must match.`,
        });
      }
      steps.push({
        id: "compose-file",
        title: "Create a folder and save docker-compose.yml",
        body: "Create an empty directory (e.g. ~/spoolman) and save this file in it as docker-compose.yml.",
        artifactIds: ["compose"],
        notes: composeNotes.length > 0 ? composeNotes : undefined,
      });
      steps.push({
        id: "start",
        title: "Start it",
        body: `Then open http://<host>:7912${cfg.subPath ? ` (or ${cfg.subPath} through your proxy)` : ""}.`,
        commands: ["docker compose up -d"],
        notes: [armv7Note],
      });
      break;
    }
    case "native": {
      steps.push({
        id: "install",
        title: "Install with one line",
        body: "Fetches the latest release and runs the installer: it sets up uv, the Python environment, and an optional systemd service (named Spoolman). The UI then runs on http://<host>:7912.",
        commands: fragmentCommands("native-install.sh"),
        notes: [armv7Note],
      });
      if (cfg.klipper) {
        steps.push({
          id: "kiauh",
          title: "Prefer KIAUH? (alternative to step 1)",
          body: "If you set up your printer with KIAUH v6, add our community extension and install from its menu instead — it performs the same native install and offers to register all the Moonraker wiring below automatically.",
          commands: fragmentCommands("kiauh-install.sh"),
        });
      }
      steps.push({
        id: "configure-env",
        title: "Configure .env",
        body: "The installer creates .env from .env.example. Replace it with this (or merge the lines you need), then restart: sudo systemctl restart Spoolman.",
        artifactIds: ["env"],
        notes:
          cfg.database !== "sqlite"
            ? [
                {
                  level: "info",
                  id: "native-external-db",
                  text: "The installer does not provision a database server — point the SPOOLMAN_DB_* variables at an existing one you manage.",
                },
              ]
            : undefined,
      });
      break;
    }
    case "helm": {
      if (cfg.database !== "sqlite") {
        steps.push({
          id: "db-secret",
          title: "Create the database password secret",
          body: "The chart bundles no database — point SPOOLMAN_DB_HOST at one you run. The password is mounted from a Secret (never in values):",
          commands: [
            `kubectl create secret generic ${DB_SECRET_NAME} --from-literal=password='${DB_PASSWORD_PLACEHOLDER}'`,
          ],
        });
      }
      steps.push({
        id: "values",
        title: "Save values.yaml",
        artifactIds: ["values"],
        notes:
          cfg.extras.puidPgid !== null
            ? [
                {
                  level: "info",
                  id: "puid-ignored-on-k8s",
                  text: "PUID/PGID are ignored under the chart's non-root securityContext (runAsUser 1000) — ownership is handled by fsGroup instead, so nothing to configure.",
                },
              ]
            : undefined,
      });
      steps.push({
        id: "helm-install",
        title: "Install the chart",
        body: "Defaults: one replica (the bundled SQLite database is single-writer), a 1 Gi PVC, health probes, non-root security context.",
        commands: ["helm install spoolman oci://ghcr.io/sherrmann/charts/spoolman-ng -f values.yaml"],
      });
      steps.push({
        id: "access",
        title: "Open the UI",
        body:
          cfg.proxy !== "none"
            ? `Via your Ingress: http(s)://spoolman.example.com${cfg.subPath ?? ""}.`
            : "No Ingress configured — reach it with kubectl port-forward against the service the chart created (kubectl get svc), or add ingress: to values.yaml later.",
      });
      break;
    }
    case "ha-addon": {
      steps.push({
        id: "addon-repo",
        title: "Add the add-on repository and install",
        body: `In Home Assistant: Settings → Add-ons → Add-on Store → ⋮ → Repositories → add ${ADDON_REPO_URL}, then install the Spoolman NG add-on.`,
      });
      steps.push({
        id: "addon-options",
        title: "Configure it in the add-on options",
        body: "Database, port, timezone and the other settings are set in the add-on's Configuration tab (they map to the same SPOOLMAN_* variables); data lives in the add-on's /data volume. Exposure/HTTPS follows your Home Assistant setup.",
      });
      break;
    }
    case "third-party-chart": {
      steps.push({
        id: "chart-override",
        title: "Point your catalog's Spoolman entry at the Spoolman-NG image",
        body: "Deploying from a catalog that pins the upstream image (TrueCharts on TrueNAS SCALE, any Helm-style app store)? Spoolman-NG is image-drop-in — override the image repository and keep everything else unchanged:",
        code: {
          language: "yaml",
          content:
            "image:\n  repository: ghcr.io/sherrmann/spoolman-ng\n  tag: latest # or a pinned YYYY.M.PATCH release\n",
        },
        notes: [
          {
            level: "info",
            id: "drop-in-invariants",
            text: "Container port 8000, the /home/app/.local/share/spoolman data volume, the SPOOLMAN_* environment variables, and the /api/v1/health probe all match upstream.",
          },
        ],
      });
      if (cfg.subPath) {
        steps.push({
          id: "chart-subpath",
          title: `Serving under ${cfg.subPath}`,
          body: `Set the SPOOLMAN_BASE_PATH environment variable to ${cfg.subPath} in your chart's env values, and adjust its health-probe path to ${cfg.subPath}/api/v1/health — both together, or the pod never goes Ready.`,
        });
      }
      break;
    }
  }

  if (cfg.platform === "compose" || cfg.platform === "native") steps.push(...proxySteps(cfg));
  if (cfg.klipper && cfg.platform === "native") steps.push(klipperUpdaterStep());
  if (cfg.klipper) steps.push(klipperTrackingStep(cfg));
  steps.push(...nfcSteps(cfg));
  return steps;
}

function updateSteps(cfg: WizardConfig): Step[] {
  switch (cfg.platform) {
    case "compose":
      return [
        {
          id: "update-compose",
          title: "Pull the new image and restart",
          body: "Run in the directory with your docker-compose.yml. Database migrations run automatically on startup.",
          commands: ["docker compose pull", "docker compose up -d"],
        },
      ];
    case "native": {
      const steps: Step[] = [];
      if (cfg.installedBefore20260719) {
        steps.push({
          id: "release-info-fix",
          title: "One-time fix for installs set up before 2026-07-19",
          body: "Older releases shipped a release_info.json whose project name does not match the repository, and Moonraker trusts that file over your configured repo: — update checks fail until it is corrected. Fix it once:",
          commands: fragmentCommands("release-info-fix.sh"),
        });
      }
      if (cfg.klipper) {
        steps.push({
          id: "update-from-printer-ui",
          title: "Update from Mainsail/Fluidd",
          body: "With [update_manager Spoolman] configured, Spoolman-NG appears in your printer UI's update list — update it there. Not set up yet? Add it now:",
          commands: ['echo "Spoolman" >> ~/printer_data/moonraker.asvc', "sudo systemctl restart moonraker"],
          artifactIds: ["moonraker-update-manager"],
        });
        steps.push({
          id: "update-native",
          title: "Or update from the shell",
          commands: fragmentCommands("native-update.sh"),
        });
      } else {
        steps.push({
          id: "update-native",
          title: "Run the updater",
          body: "Overlays the new release onto the install (.env, .venv and the local uv toolchain are preserved), re-syncs dependencies, and restarts the Spoolman service.",
          commands: fragmentCommands("native-update.sh"),
        });
      }
      return steps;
    }
    case "helm":
      return [
        {
          id: "update-helm",
          title: "Upgrade the release",
          body: "Pass your values file again so your configuration carries over.",
          commands: ["helm upgrade spoolman oci://ghcr.io/sherrmann/charts/spoolman-ng -f values.yaml"],
        },
      ];
    case "ha-addon":
      return [
        {
          id: "update-addon",
          title: "Update from the add-on store",
          body: "Home Assistant surfaces add-on updates under Settings → Add-ons; back up from the add-on page first.",
        },
      ];
    case "third-party-chart":
      return [
        {
          id: "update-chart",
          title: "Bump the image tag in your catalog",
          body: "Re-pull :latest or move the pinned YYYY.M.PATCH tag forward in your catalog's UI; migrations run automatically on startup.",
        },
      ];
  }
}

function migrateSteps(cfg: WizardConfig): Step[] {
  switch (cfg.platform) {
    case "compose":
      return [
        {
          id: "migrate-stop",
          title: "Stop the upstream instance",
          body: "Run in the directory with your existing docker-compose.yml, after backing up your database.",
          commands: ["docker compose down"],
        },
        {
          id: "migrate-swap-image",
          title: "Swap the image in your existing compose file",
          body: "Wherever it says ghcr.io/donkie/spoolman (or donkieyo/spoolman on Docker Hub), use the Spoolman-NG image instead — ports, volume path and environment variables all stay as they are:",
          code: { language: "yaml", content: "    image: ghcr.io/sherrmann/spoolman-ng:latest\n" },
        },
        {
          id: "migrate-start",
          title: "Start it back up",
          body: "Spoolman-NG points at your existing database (or data directory) and migrates the schema automatically on first start.",
          commands: ["docker compose up -d"],
          notes: cfg.klipper ? [spoolmanUrlUnchangedNote] : undefined,
        },
      ];
    case "native": {
      const steps: Step[] = [
        {
          id: "migrate-stop",
          title: "Back up, then stop the old service",
          body: "Your data directory (~/.local/share/spoolman by default) is separate from the install directory and is preserved — back it up anyway.",
          commands: ["sudo systemctl stop Spoolman"],
        },
        {
          id: "migrate-install",
          title: "Install Spoolman-NG over it",
          body: "The zip unpacks into ~/Spoolman (the upstream default too); the installer keeps your data directory untouched and migrates the schema on first start.",
          commands: fragmentCommands("native-install.sh"),
        },
        {
          id: "configure-env",
          title: "Configure .env",
          body: "Re-apply any custom settings from your old install, then start the service: sudo systemctl start Spoolman.",
          artifactIds: ["env"],
        },
      ];
      if (cfg.klipper) {
        steps.push({
          id: "klipper-updater",
          title: "Replace the Moonraker update recipe",
          body: "Your old [update_manager] section points at upstream Spoolman — replace it with the Spoolman-NG recipe (and make sure moonraker.asvc has a Spoolman line), then restart Moonraker:",
          commands: ['echo "Spoolman" >> ~/printer_data/moonraker.asvc', "sudo systemctl restart moonraker"],
          artifactIds: ["moonraker-update-manager"],
          notes: [spoolmanUrlUnchangedNote],
        });
      }
      return steps;
    }
    case "helm":
      return [
        {
          id: "values",
          title: "Save values.yaml",
          body: "Running upstream on Kubernetes today? Install the official Spoolman-NG chart with your existing database settings — an external database is migrated in place on first start. For SQLite on a PVC, reuse the claim via persistence.existingClaim (commented in the file).",
          artifactIds: ["values"],
        },
        {
          id: "helm-install",
          title: "Install the chart",
          commands: ["helm install spoolman oci://ghcr.io/sherrmann/charts/spoolman-ng -f values.yaml"],
          notes: cfg.klipper ? [spoolmanUrlUnchangedNote] : undefined,
        },
      ];
    case "ha-addon":
      return [
        {
          id: "migrate-addon",
          title: "Install the add-on, then restore your backup",
          body: `Add ${ADDON_REPO_URL} in Home Assistant and install the Spoolman NG add-on, then restore your database backup into its /data volume (see the add-on docs).`,
        },
      ];
    case "third-party-chart":
      return [
        {
          id: "chart-override",
          title: "Override the image repository in your catalog",
          body: "Spoolman-NG is image-drop-in for upstream charts (TrueCharts and friends): override the image repository to ghcr.io/sherrmann/spoolman-ng and keep everything else unchanged. Your existing database is migrated automatically on the first start.",
          code: {
            language: "yaml",
            content:
              "image:\n  repository: ghcr.io/sherrmann/spoolman-ng\n  tag: latest # or a pinned YYYY.M.PATCH release\n",
          },
          notes: cfg.klipper ? [spoolmanUrlUnchangedNote] : undefined,
        },
      ];
  }
}

function switchSteps(cfg: WizardConfig): Step[] {
  if (cfg.platform === "compose") {
    // native → docker
    return [
      {
        id: "switch-stop-native",
        title: "Stop the native service",
        commands: ["sudo systemctl stop Spoolman"],
      },
      {
        id: "compose-file",
        title: "Create a folder and save docker-compose.yml",
        body: "Create an empty directory (e.g. ~/spoolman) and save this file in it as docker-compose.yml.",
        artifactIds: ["compose"],
      },
      {
        id: "switch-copy-data",
        title: "Copy your data into the bind mount",
        body: "Your data lives in one place regardless of install method — switching is just moving the data directory.",
        commands: ["mkdir -p ./data", "cp -a ~/.local/share/spoolman/. ./data/"],
        notes: [stopBothSidesNote],
      },
      {
        id: "start",
        title: "Start it",
        commands: ["docker compose up -d"],
        notes: cfg.klipper ? [spoolmanUrlUnchangedNote] : undefined,
      },
      {
        id: "switch-cleanup",
        title: "Once happy, remove the native install",
        body: `Disable the systemd unit and delete ~/Spoolman — keep the old data directory until you've verified the Docker install (see Uninstalling in the installation guide: ${DOCS_URL}).`,
      },
    ];
  }
  // docker → native
  const steps: Step[] = [
    {
      id: "switch-stop-docker",
      title: "Stop the container",
      body: "Run in the directory with your docker-compose.yml.",
      commands: ["docker compose down"],
    },
    {
      id: "install",
      title: "Install natively with one line",
      commands: fragmentCommands("native-install.sh"),
      notes: [armv7Note],
    },
    {
      id: "configure-env",
      title: "Configure .env",
      body: "Carry your settings over from the compose file's environment: block, then restart: sudo systemctl restart Spoolman.",
      artifactIds: ["env"],
    },
    {
      id: "switch-copy-data",
      title: "Copy your data out of the bind mount",
      body: "Run from the old compose directory.",
      commands: ["cp -a ./data/. ~/.local/share/spoolman/"],
      notes: [stopBothSidesNote],
    },
  ];
  if (cfg.klipper) {
    steps.push({
      ...klipperUpdaterStep(),
      title: "One-click updates now apply",
      body:
        "A perk of the native install: Moonraker can update Spoolman-NG from Mainsail/Fluidd. " +
        klipperUpdaterStep().body,
      notes: [...(klipperUpdaterStep().notes ?? []), spoolmanUrlUnchangedNote],
    });
  }
  return steps;
}

export function buildSteps(effective: WizardConfig, artifacts: Artifact[]): Step[] {
  const steps = (() => {
    switch (effective.goal) {
      case "fresh":
        return freshSteps(effective);
      case "update":
        return updateSteps(effective);
      case "migrate-upstream":
        return migrateSteps(effective);
      case "switch":
        return switchSteps(effective);
    }
  })();

  // Never reference an artifact that wasn't generated (test-enforced invariant).
  const known = new Set(artifacts.map((a) => a.id));
  for (const step of steps) {
    const missing = (step.artifactIds ?? []).filter((id) => !known.has(id));
    if (missing.length > 0) {
      throw new Error(`Step ${step.id} references missing artifacts: ${missing.join(", ")}`);
    }
  }
  return steps;
}
