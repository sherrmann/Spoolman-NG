import type { WizardConfig } from "../config";
import { wantsUpdateManager } from "../rules";
import type { Artifact } from "../types";
import { composeArtifact } from "./compose";
import { envArtifact } from "./env";
import { helmValuesArtifact } from "./helmValues";
import { spoolmanStanzaArtifact, updateManagerArtifact } from "./moonraker";
import { proxyArtifact } from "./proxy";

/**
 * Which file artifacts a (normalized) configuration produces. Steps reference
 * these by id. ha-addon and third-party-chart platforms configure everything in
 * their own UIs, so they only ever emit the Moonraker client stanza.
 */
export function buildArtifacts(effective: WizardConfig): Artifact[] {
  const artifacts: Artifact[] = [];
  const platform = effective.platform;

  switch (effective.goal) {
    case "fresh":
      if (platform === "compose") artifacts.push(composeArtifact(effective));
      if (platform === "native") artifacts.push(envArtifact(effective));
      if (platform === "helm") artifacts.push(helmValuesArtifact(effective));
      if (platform === "compose" || platform === "native") {
        const proxy = proxyArtifact(effective);
        if (proxy) artifacts.push(proxy);
      }
      if (effective.klipper) artifacts.push(spoolmanStanzaArtifact());
      if (wantsUpdateManager(effective)) artifacts.push(updateManagerArtifact());
      break;

    case "update":
      // Existing installs keep their config; the only artifact worth offering is
      // the one-click updater recipe for Klipper users who haven't set it up yet.
      if (wantsUpdateManager(effective)) artifacts.push(updateManagerArtifact());
      break;

    case "migrate-upstream":
      if (platform === "native") artifacts.push(envArtifact(effective));
      if (platform === "helm") artifacts.push(helmValuesArtifact(effective));
      // Their old [update_manager] recipe pointed at upstream — replace it.
      if (wantsUpdateManager(effective)) artifacts.push(updateManagerArtifact());
      break;

    case "switch":
      if (platform === "compose") artifacts.push(composeArtifact(effective));
      if (platform === "native") {
        artifacts.push(envArtifact(effective));
        if (wantsUpdateManager(effective)) artifacts.push(updateManagerArtifact());
      }
      break;
  }

  return artifacts;
}
