// Builders for the JavaScript injected into the WebView. Pure string
// construction so the escaping rules are unit-testable.
//
// The localStorage key is the web client's token seam
// (client/src/utils/apiToken.ts) — the one contract the shell shares with the
// hosted UI. The web app itself attaches the token to axios, fetch and the
// websocket once the key is present.

import { originOf } from "./serverProfile";

export const TOKEN_STORAGE_KEY = "spoolmanApiToken";

export const TOKEN_MESSAGE_TYPE = "spoolman-token";

/**
 * Normalize an origin for comparison with the browser's `location.origin`:
 * lowercase scheme and host, default ports stripped. Unrecognized values are
 * returned unchanged, so a malformed origin simply never matches (fail-closed).
 */
export function normalizeOrigin(origin: string): string {
  const m = origin.match(/^(https?):\/\/([^/:]+)(?::(\d+))?$/i);
  if (!m) return origin;
  const scheme = m[1].toLowerCase();
  const host = m[2].toLowerCase();
  const port = m[3];
  const isDefault = (scheme === "http" && port === "80") || (scheme === "https" && port === "443");
  return port && !isDefault ? `${scheme}://${host}:${port}` : `${scheme}://${host}`;
}

/**
 * Script run before page load on every navigation: seed the stored token (if
 * the shell has one) and mirror later token changes back to the shell, so a
 * login performed inside the web UI survives app restarts.
 *
 * The whole script is gated on the configured server origin (#220): forward-auth
 * portals and IdPs load in-WebView by design, and the token must never be
 * written to - or the mirror run inside - a foreign origin's page.
 */
export function buildStartupInjection(token: string | null, serverOrigin: string): string {
  const seed = token
    ? `try{localStorage.setItem(${JSON.stringify(TOKEN_STORAGE_KEY)},${JSON.stringify(token)});}catch(e){}`
    : "";
  const mirror =
    `(function(){var last=${token ? JSON.stringify(token) : "null"};` +
    `setInterval(function(){try{` +
    `var t=localStorage.getItem(${JSON.stringify(TOKEN_STORAGE_KEY)});` +
    `if(t!==last){last=t;` +
    `if(window.ReactNativeWebView){window.ReactNativeWebView.postMessage(JSON.stringify({type:${JSON.stringify(
      TOKEN_MESSAGE_TYPE,
    )},token:t}));}` +
    `}}catch(e){}},2000);})();`;
  return `if(location.origin===${JSON.stringify(normalizeOrigin(serverOrigin))}){${seed}${mirror}}true;`;
}

/** Script that navigates the SPA to an absolute URL (full page load — reliable everywhere). */
export function buildNavigateScript(url: string): string {
  return `location.assign(${JSON.stringify(url)});true;`;
}

export interface TokenMessage {
  type: typeof TOKEN_MESSAGE_TYPE;
  token: string | null;
}

/**
 * Parse a WebView postMessage payload, returning the token message or null.
 *
 * Requires the posting frame's URL and the configured server origin (#220): any
 * page loaded in the WebView can call postMessage, and a foreign page must not
 * be able to overwrite or clear the stored token.
 */
export function parseWebViewMessage(data: string, frameUrl: string, serverOrigin: string): TokenMessage | null {
  if (normalizeOrigin(originOf(frameUrl)) !== normalizeOrigin(serverOrigin)) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(data);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      (parsed as { type?: unknown }).type === TOKEN_MESSAGE_TYPE
    ) {
      const token = (parsed as { token?: unknown }).token;
      return { type: TOKEN_MESSAGE_TYPE, token: typeof token === "string" && token ? token : null };
    }
  } catch {
    /* not JSON — not ours */
  }
  return null;
}
