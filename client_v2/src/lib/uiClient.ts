/**
 * The per-browser switch between this fork's two web clients: the legacy React one and this
 * Svelte one. The backend decides which bundle to serve by reading a `spoolman_ui` cookie
 * (`"react"` | `"svelte"`); an absent or unrecognised value falls back to the server's own
 * default. This module is the client-side half of that contract -- writing the cookie, and
 * deciding whether the control is worth showing at all -- kept free of Svelte so it can be
 * unit-tested without a DOM.
 *
 * There is no service worker to unregister here, unlike the React client: a plain cookie
 * write plus a top-level reload is the whole action.
 */

export type UiClientTarget = 'react' | 'svelte';

const COOKIE_NAME = 'spoolman_ui';
const COOKIE_MAX_AGE_S = 31536000; // 1 year

/**
 * Whether the switcher belongs on the Settings page at all.
 *
 * Both inputs come straight off GET /info. An operator can disable switching outright
 * (SPOOLMAN_UI_SWITCHER=FALSE), and a source install may have built only one of the two
 * bundles -- in which case there is nothing to switch *to*. `clientsAvailable` defaulting to
 * `[]` and `clientSwitchEnabled` defaulting to `false` (see $lib/stores/serverInfo) means an
 * older backend that never sends these fields, or a request still in flight, fails closed to
 * "hidden" rather than showing a control with nothing to do.
 */
export function shouldShowUiSwitcher(clientSwitchEnabled: boolean, clientsAvailable: string[]): boolean {
	return clientSwitchEnabled && clientsAvailable.includes('react') && clientsAvailable.includes('svelte');
}

/**
 * Record which client this browser wants, then reload so the backend picks it up.
 *
 * `document`/`location` are read off `globalThis` rather than the bare identifiers so a test
 * can stub them without a DOM (see uiClient.test.ts) -- the same trick $lib/api/auth uses.
 */
export function switchUiClient(target: UiClientTarget): void {
	globalThis.document.cookie = `${COOKIE_NAME}=${target}; path=/; max-age=${COOKIE_MAX_AGE_S}; SameSite=Lax`;
	globalThis.location.reload();
}
