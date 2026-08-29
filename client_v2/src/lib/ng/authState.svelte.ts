// What this client knows about authentication, for the UI to react to.
//
// The credential itself lives in ./authToken.ts, which is deliberately rune-free
// so the transport can read it synchronously. This is the other half: the state
// a component can bind to, and the one place that asks the server what it wants.
//
// GET /auth/status is an open route -- it answers without credentials even when
// everything else is refused -- so it is safe to call on startup and is how the
// prompt knows whether to ask for a username and password or for a shared token.

import { API_BASE } from '$lib/api/config';
import { getJson, HttpError } from '$lib/api/http';
import { clearToken, onCredentialsRequired, setToken } from './authToken';

interface AuthStatus {
	auth_required?: boolean;
	accounts_enabled?: boolean;
}

interface LoginResponse {
	access_token: string;
	username: string;
	role: string;
}

class AuthState {
	/** The server wants credentials from somebody. False when auth is switched off. */
	required = $state(false);
	/** User accounts exist, so ask for a username and password rather than a token. */
	accountsEnabled = $state(false);
	/** The prompt is up: we were refused and have nothing valid to retry with. */
	prompting = $state(false);
	loaded = $state(false);

	/** Ask the server what it requires. Never throws; a failure just leaves the defaults. */
	async load(): Promise<void> {
		try {
			const status = await getJson<AuthStatus>('/auth/status');
			this.required = status.auth_required === true;
			this.accountsEnabled = status.accounts_enabled === true;
		} catch (e) {
			// Not fatal: if the server does want credentials, the first refused request
			// raises the prompt anyway. Older backends have no /auth/status at all.
			console.error('Failed to load auth status', e);
		} finally {
			this.loaded = true;
		}
	}

	/**
	 * Raise the prompt. Called by the transport when a request comes back asking
	 * for credentials, so it also re-reads status: an operator may have turned
	 * accounts on since the page loaded, which changes what we should ask for.
	 */
	prompt(): void {
		if (this.prompting) return;
		this.prompting = true;
		void this.load();
	}

	/** Exchange a username and password for a token. Throws with the server's message. */
	async login(username: string, password: string): Promise<void> {
		const res = await postLogin('/auth/login', { username, password });
		setToken(res.access_token);
		this.accept();
	}

	/** Take an operator's shared token at face value; the next request proves it. */
	acceptToken(token: string): void {
		setToken(token.trim());
		this.accept();
	}

	/** Start again with no credential — used when a stored one turns out to be stale. */
	forget(): void {
		clearToken();
		this.prompting = true;
	}

	/**
	 * Reload once a credential is in hand.
	 *
	 * Everything already on screen was fetched without one, and the websockets
	 * were refused their handshake. Re-running the app is both the simplest and
	 * the most complete way to pick all of that up, and matches what the React
	 * client does after the same step.
	 */
	private accept(): void {
		this.prompting = false;
		if (typeof globalThis.location !== 'undefined') globalThis.location.reload();
	}
}

/**
 * POST without going through http.ts's postJson, because a failed login is an
 * expected answer rather than a transport fault: postJson would route its 401
 * straight back into the credential prompt we are already standing in.
 */
async function postLogin(path: string, body: unknown): Promise<LoginResponse> {
	const res = await fetch(API_BASE + path, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!res.ok) {
		let message = '';
		try {
			const parsed = (await res.json()) as Record<string, unknown>;
			// The login route answers with FastAPI's `detail`; the auth middleware
			// uses `message`. Read both rather than guessing which one arrived.
			const raw = parsed.detail ?? parsed.message;
			if (typeof raw === 'string') message = raw;
		} catch {
			/* no body, or not JSON */
		}
		throw new HttpError(message || `Login failed (${res.status})`, res.status);
	}
	return (await res.json()) as LoginResponse;
}

export const authState = new AuthState();

// Bridge the transport's "we need a credential" signal to this state. Registered
// at module load so a 401 arriving before the shell mounts is not dropped.
onCredentialsRequired(() => authState.prompt());
