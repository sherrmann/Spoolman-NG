/**
 * The human-readable part of a failed request.
 *
 * The backend answers in two dialects. Routes that raise FastAPI's HTTPException -- the whole
 * of /auth -- put the text under `detail`; everything else, and the auth middleware itself,
 * returns a `Message` with it under `message`. Upstream's HttpError only reads the second, so
 * "Cannot delete the last administrator." would otherwise reach the user as
 * "DELETE /auth/users/3 → 400". The React client reads both (client/src/utils/auth.ts).
 */
import { HttpError } from '$lib/api/http';

export function apiErrorMessage(e: unknown, fallback = ''): string {
	if (e instanceof HttpError) {
		const detail = e.body?.detail;
		if (typeof detail === 'string' && detail) return detail;
		const message = e.body?.message;
		if (typeof message === 'string' && message) return message;
		return fallback || e.message;
	}
	if (e instanceof Error && e.message) return e.message;
	return fallback;
}
