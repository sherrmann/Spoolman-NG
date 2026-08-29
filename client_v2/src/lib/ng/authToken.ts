// The bearer credential this client sends, and where it is kept.
//
// Two things can authenticate a request here: the operator's shared
// SPOOLMAN_API_TOKEN, and the token POST /auth/login mints for a user account.
// The server does not distinguish them on the wire -- both travel as
// `Authorization: Bearer <value>` -- so neither does this module.
//
// Kept deliberately free of runes. `http.ts`, `config.ts`'s wsUrl() and the two
// websocket clients read the token per request and per reconnect, outside any
// component and outside any effect, so it has to be readable synchronously from
// plain module scope. The reactive half a UI needs lives in ./authState.svelte.ts
// and layers on top of this.
//
// The storage key is shared with the React client on purpose. Both clients are
// served from the same origin and a cookie decides which one answers, so a user
// who logs in and then switches interface would otherwise arrive logged out.

const TOKEN_KEY = 'spoolmanApiToken';

// Mirrors the stored value so the token still works for the life of the page
// when storage is unavailable (private mode, blocked cookies) -- the user is
// asked once per tab rather than on every request.
let memoryToken: string | null = null;

export function getToken(): string | null {
	if (memoryToken !== null) return memoryToken;
	try {
		return globalThis.localStorage?.getItem(TOKEN_KEY) ?? null;
	} catch {
		return null;
	}
}

export function setToken(token: string): void {
	memoryToken = token;
	try {
		globalThis.localStorage?.setItem(TOKEN_KEY, token);
	} catch {
		/* see getToken -- the in-memory copy carries this tab */
	}
}

export function clearToken(): void {
	memoryToken = null;
	try {
		globalThis.localStorage?.removeItem(TOKEN_KEY);
	} catch {
		/* nothing stored to clear */
	}
}

/** `{ Authorization }` when a token is held, or nothing at all when it is not. */
export function authHeaders(): Record<string, string> {
	const token = getToken();
	return token ? { Authorization: `Bearer ${token}` } : {};
}

// Asking for a credential. The transport discovers it needs one (a 401 carrying
// `WWW-Authenticate: Bearer`), but the transport cannot draw a dialog, and the
// dialog cannot import the transport without a cycle. One listener, registered
// by the app shell, bridges the two. Kept here rather than in a rune module so
// `api/auth.ts` can import it without pulling the Svelte compiler into its unit
// tests.
let credentialListener: (() => void) | null = null;

/** Register the prompt. Returns a disposer, for symmetry with Svelte effects. */
export function onCredentialsRequired(fn: () => void): () => void {
	credentialListener = fn;
	return () => {
		if (credentialListener === fn) credentialListener = null;
	};
}

/** The server asked for credentials we do not have. No-op before the shell mounts. */
export function requireCredentials(): void {
	credentialListener?.();
}

/**
 * Append the token to a websocket URL.
 *
 * Browsers cannot set headers on a WebSocket handshake, so the server accepts
 * `?token=` there instead (spoolman/auth.py). Reconnects rebuild the URL through
 * this, so a token stored after the first failed attempt is picked up.
 */
export function withWsToken(url: string): string {
	const token = getToken();
	if (!token) return url;
	return url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token);
}
