import type { WizardConfig } from "../config";
import { renderFragment } from "../fragments";
import { CADDY_UPSTREAM_PLACEHOLDER, HOSTNAME_PLACEHOLDER, NGINX_UPSTREAM_PLACEHOLDER } from "../placeholders";
import type { Artifact } from "../types";

/**
 * Rule 6: standalone proxy snippets exist for Caddy and nginx at the root path.
 * Traefik is expressed as compose labels (merged into the compose artifact) and
 * sub-path serving on Caddy/nginx gets guidance notes instead of an untested
 * snippet (rule 5) — the docs only carry root-path examples for those two.
 */
export function proxyArtifact(cfg: WizardConfig): Artifact | null {
  if (cfg.subPath) return null;
  if (cfg.proxy === "caddy") {
    return {
      id: "proxy-caddy",
      filename: "Caddyfile",
      language: "caddy",
      title: "Caddyfile",
      content: renderFragment("caddy.Caddyfile", {
        HOSTNAME: HOSTNAME_PLACEHOLDER,
        UPSTREAM: CADDY_UPSTREAM_PLACEHOLDER,
      }),
    };
  }
  if (cfg.proxy === "nginx") {
    return {
      id: "proxy-nginx",
      filename: "spoolman-nginx.conf",
      language: "nginx",
      title: "nginx — inside your server { } block",
      content: renderFragment("nginx-location.conf", { UPSTREAM: NGINX_UPSTREAM_PLACEHOLDER }),
    };
  }
  return null;
}
