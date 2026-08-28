import { unregisterServiceWorkers } from "./authReloadHandler";
import type { IInfo } from "./useInfo";

/** Name of the per-browser cookie that tells the backend which client to serve next request. */
export const UI_CLIENT_COOKIE_NAME = "spoolman_ui";

/** Recognised cookie values. Anything else (absent, unrecognised) means "use the server default". */
export type UiClient = "react" | "svelte";

/**
 * Switches the UI client this browser is served by: writes the `spoolman_ui` cookie, then
 * reloads so the backend picks it up on the next request.
 *
 * Only switching *to* svelte unregisters service workers first. The React client registers a
 * workbox worker at `<base>/sw.js` (index.tsx) whose registration and asset precache outlive the
 * switch. It cannot hijack navigations — vite.config.ts sets `navigateFallback: null` precisely so
 * every navigation reaches the server — so this is not about being served the old shell; it is
 * about leaving a worker for a client that is no longer being served, holding a precache of its
 * assets. `client_v2/static/sw.js` is a self-destructing worker written to tear that registration
 * down, but it only runs when the browser next checks for a worker update, which is nowhere near
 * prompt enough for a switch the user just asked for. Doing it here makes it immediate. Switching
 * back to react needs no such step — client_v2 registers no worker of its own, and index.tsx
 * re-registers React's on boot.
 */
export async function switchUiClient(target: UiClient): Promise<void> {
  document.cookie = `${UI_CLIENT_COOKIE_NAME}=${target}; path=/; max-age=31536000; SameSite=Lax`;
  if (target === "svelte") {
    await unregisterServiceWorkers();
  }
  window.location.reload();
}

/**
 * Whether the switch-client control should render at all, given the current `/info` response.
 *
 * Both of the following must hold:
 * - the operator has not disabled switching (`client_switch_enabled === true`);
 * - both bundles are actually built on this server (`clients_available` has both entries — a
 *   source install may have built only one).
 *
 * Both clients are served from the same origin and the same manifest scope and the switch is a
 * plain document reload, so this holds inside an installed PWA too — matching the Svelte client,
 * which has no such guard either.
 *
 * `info` is `undefined` while `/info` is still loading, and the three fields are all optional so
 * an older backend that predates this feature omits them — both cases render nothing.
 */
export function shouldShowUiClientSwitch(info: IInfo | undefined): boolean {
  if (!info) return false;
  if (info.client_switch_enabled !== true) return false;
  const available = info.clients_available;
  return !!available && available.includes("react") && available.includes("svelte");
}
