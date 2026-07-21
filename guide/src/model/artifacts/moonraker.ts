import { renderFragment } from "../fragments";
import { SPOOLMAN_URL_PLACEHOLDER } from "../rules";
import type { Artifact } from "../types";

/** Rule 2: the [spoolman] client stanza — one per printer, any platform. */
export function spoolmanStanzaArtifact(): Artifact {
  return {
    id: "moonraker-spoolman",
    filename: "moonraker-spoolman.ini",
    language: "ini",
    title: "moonraker.conf — [spoolman] (filament tracking; add on every printer)",
    content: renderFragment("moonraker-spoolman.ini", { SPOOLMAN_URL: SPOOLMAN_URL_PLACEHOLDER }),
  };
}

/** Rule 3: the one-click updater recipe — native installs only. */
export function updateManagerArtifact(): Artifact {
  return {
    id: "moonraker-update-manager",
    filename: "moonraker-update-manager.ini",
    language: "ini",
    title: "moonraker.conf — [update_manager Spoolman] (one-click updates)",
    content: renderFragment("moonraker-update-manager.ini"),
  };
}
