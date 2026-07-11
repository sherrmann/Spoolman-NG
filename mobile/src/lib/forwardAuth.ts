// Detection for a "forward-auth" gateway (Authelia, Authentik, oauth2-proxy,
// Traefik ForwardAuth, Caddy forward_auth, …) sitting in front of the server.
//
// Such a gateway intercepts EVERY request before it reaches Spoolman and, when
// there is no valid session cookie, answers with 401/403 (or a redirect) that
// points at a separate login portal. Because Spoolman's own /info is public
// even when its auth is enabled, a 401/403 there can only come from something
// in front — so it is a reliable "you must sign in at the portal first" signal.
//
// The fix at runtime is cookie-based: the user completes the portal login
// inside the WebView, the session cookie lands in the shared cookie jar, and
// native fetches (probe, NFC lookup) then carry it too. This module only does
// the detection and message-shaping; it is pure so it can be unit-tested.

import { originOf } from "./serverProfile";

/**
 * Thrown by probeServer when the server sits behind a forward-auth gateway.
 * Carries the portal URL when we can recover it from the response, purely so
 * the UI can name the portal — sign-in still happens in the WebView.
 */
export class ForwardAuthError extends Error {
  authUrl: string | null;

  constructor(authUrl: string | null) {
    super(
      authUrl
        ? `Server is behind a login portal (${authUrl})`
        : "Server is behind a login portal",
    );
    this.name = "ForwardAuthError";
    this.authUrl = authUrl;
  }
}

export interface ForwardAuthProbe {
  /** HTTP status of the failed request to a public endpoint (/info). */
  status: number;
  /** Response body, if any — used to recover the portal URL. */
  body?: string;
  /** The URL the request ended on (after any redirects the fetch followed). */
  finalUrl?: string;
  /** The server base URL we were probing. */
  baseUrl: string;
}

const PORTAL_MARKERS = /\b(authelia|authentik|oauth2[-_ ]?proxy|keycloak|single[- ]?sign|forwardauth)\b/i;

/**
 * Decide whether a failed probe of the public /info endpoint is a forward-auth
 * wall rather than a genuine "server not found / wrong URL" failure.
 *
 * Signals, any of which is sufficient:
 *  - 401/403 on /info — Spoolman never protects /info, so a gateway did it;
 *  - the request was redirected to a different origin (the portal);
 *  - the body names a known portal or links off-origin.
 */
export function looksLikeForwardAuth(probe: ForwardAuthProbe): boolean {
  if (probe.status === 401 || probe.status === 403) {
    return true;
  }
  const baseOrigin = originOf(probe.baseUrl);
  if (probe.finalUrl) {
    const finalOrigin = originOf(probe.finalUrl);
    if (/^https?:\/\//i.test(finalOrigin) && finalOrigin !== baseOrigin) {
      return true;
    }
  }
  const body = probe.body ?? "";
  if (PORTAL_MARKERS.test(body)) {
    return true;
  }
  const linked = extractAuthUrl(body);
  return linked !== null && originOf(linked) !== baseOrigin;
}

/**
 * Best-effort recovery of the portal URL from a forward-auth response body,
 * e.g. Authelia's `<a href="https://auth.example/?rd=...">401 Unauthorized</a>`.
 * Returns an absolute http(s) URL or null. Only used for display.
 */
export function extractAuthUrl(body: string | undefined): string | null {
  if (!body) {
    return null;
  }
  const decoded = decodeEntities(body);
  const href = decoded.match(/href\s*=\s*["']?(https?:\/\/[^"'\s>]+)/i);
  if (href) {
    return href[1];
  }
  // Some gateways only put the destination in an `rd=` redirect parameter.
  const rd = decoded.match(/[?&]rd=([^"'\s&]+)/i);
  if (rd) {
    try {
      const target = decodeURIComponent(rd[1]);
      if (/^https?:\/\//i.test(target)) {
        return target;
      }
    } catch {
      /* malformed percent-encoding — give up on recovery */
    }
  }
  return null;
}

function decodeEntities(value: string): string {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&#x2F;/gi, "/")
    .replace(/&#47;/g, "/")
    .replace(/&quot;/g, '"')
    .replace(/&#x3D;/gi, "=");
}
