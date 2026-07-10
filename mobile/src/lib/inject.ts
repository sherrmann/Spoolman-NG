// Builders for the JavaScript injected into the WebView. Pure string
// construction so the escaping rules are unit-testable.
//
// The localStorage key is the web client's token seam
// (client/src/utils/apiToken.ts) — the one contract the shell shares with the
// hosted UI. The web app itself attaches the token to axios, fetch and the
// websocket once the key is present.

export const TOKEN_STORAGE_KEY = "spoolmanApiToken";

export const TOKEN_MESSAGE_TYPE = "spoolman-token";

/**
 * Script run before page load on every navigation: seed the stored token (if
 * the shell has one) and mirror later token changes back to the shell, so a
 * login performed inside the web UI survives app restarts.
 */
export function buildStartupInjection(token: string | null): string {
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
  return `${seed}${mirror}true;`;
}

/** Script that navigates the SPA to an absolute URL (full page load — reliable everywhere). */
export function buildNavigateScript(url: string): string {
  return `location.assign(${JSON.stringify(url)});true;`;
}

export interface TokenMessage {
  type: typeof TOKEN_MESSAGE_TYPE;
  token: string | null;
}

/** Parse a WebView postMessage payload, returning the token message or null. */
export function parseWebViewMessage(data: string): TokenMessage | null {
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
