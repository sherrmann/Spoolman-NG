/**
 * Who is looking, asked once per page load.
 *
 * Four settings panels (#413) and the AI one each decide whether to render at all from the
 * caller's role, and they mount together on one page. One memoised request answers all of
 * them; five identical `GET /auth/me` calls on every visit to /settings would be noise.
 *
 * `/auth/me` reflects the middleware's principal rather than a database row: its `id` is
 * always 0, and `username` is "anonymous" when authentication is off, "api-token" for the
 * shared token, or the account name. So identity is by username -- see isSelf in ./users.
 */
import { getJson, HttpError } from '$lib/api/http';

export interface Me {
	username: string;
	role: string;
}

let pending: Promise<Me | null> | undefined;

/**
 * The current principal, or null when the server wants credentials we do not hold.
 *
 * Anything other than a 401 -- the backend being down, or too old to have the route -- is
 * reported as an anonymous administrator, which is what the backend itself answers when
 * authentication is switched off. A hidden panel would tell the operator nothing; the panel's
 * own requests report a broken backend far better.
 */
export function whoAmI(): Promise<Me | null> {
	pending ??= getJson<Partial<Me>>('/auth/me')
		.then((me) => ({ username: String(me.username ?? ''), role: String(me.role ?? '') }))
		.catch((e: unknown) => {
			if (e instanceof HttpError && e.status === 401) return null;
			return { username: 'anonymous', role: 'admin' };
		});
	return pending;
}

/** Whether the caller may operate the settings panels. Fails closed on a refused request. */
export async function currentUserIsAdmin(): Promise<boolean> {
	return (await whoAmI())?.role === 'admin';
}

/** Forget the cached answer, e.g. after logging out or in. Tests use it between cases. */
export function resetWhoAmI(): void {
	pending = undefined;
}
