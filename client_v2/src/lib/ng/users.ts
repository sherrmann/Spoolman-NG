/**
 * User accounts (#52 / #413): the rules the panel applies before a request goes out.
 *
 * The backend is the authority on everything that matters -- the last administrator cannot be
 * deleted or demoted, a duplicate username is refused, the first account is always an admin
 * -- and the panel surfaces those refusals verbatim. What lives here is the little the client
 * decides for itself.
 */
import type { Me } from './me';
import type { User } from './types';

export type Role = 'admin' | 'readonly';

export const ROLES: readonly Role[] = ['admin', 'readonly'];

export function isRole(value: string): value is Role {
	return (ROLES as readonly string[]).includes(value);
}

/** Both fields are required. The backend's own limits are 64 characters for the username. */
export function validateNewUser(username: string, password: string): 'username' | 'password' | null {
	const u = username.trim();
	if (!u || u.length > 64) return 'username';
	if (!password) return 'password';
	return null;
}

/**
 * Whether a listed account is the one the caller is signed in with.
 *
 * `/auth/me` reports the principal's name rather than a row id (its `id` is always 0), so the
 * username is the only handle. An anonymous or token principal matches nobody.
 */
export function isSelf(me: Me | null, user: User): boolean {
	return !!me && me.role !== '' && me.username === user.username;
}
