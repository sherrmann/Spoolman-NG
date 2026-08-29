// Answering a 401, which here can mean two opposite things.
//
// This fork's Spoolman DOES have a login of its own (a shared SPOOLMAN_API_TOKEN,
// or user accounts) and answers 401 when it wants credentials, marking those
// responses with `WWW-Authenticate: Bearer`. Reloading cannot fix that one --
// there is nobody to redirect us -- so it has to raise the credential prompt
// instead. That header is the whole discriminator; see handleUnauthorized below.
//
// The other case is the one this module was written for. People run Spoolman
// behind a forward-auth proxy (Authelia, Authentik, oauth2-proxy, Caddy
// forward_auth), and those proxies treat the two kinds of request differently
// once a session goes stale:
//
//   - a top-level navigation asks for HTML, so the proxy answers 302 and sends
//     the user to its login portal with a note to return here afterwards;
//   - an in-page fetch asks for JSON, where an HTML login form would be
//     nonsense, so the proxy answers a flat 401 and leaves it to us.
//
// An already-loaded tab only ever makes the second kind. So it sits there
// looking fine while every request fails, and the user has to work out for
// themselves that a manual reload is what fixes it. Reloading on 401 does that
// for them: the reload IS a navigation, so it earns the redirect, and the user
// comes back to the page they were on.
//
// Dormant for everyone else — no proxy in front means no 401 to react to.

import { requireCredentials } from '$lib/ng/authToken';

const COOLDOWN_KEY = 'spoolman.auth-reload-at';
const COOLDOWN_MS = 30_000;

// The stamp is kept in two places on purpose, because each covers the other's
// blind spot. localStorage is the one that matters: it survives the reload, so
// a page that comes back still un-authenticated can tell it just tried. The
// in-memory copy covers the burst *before* any reload happens — a view firing
// several requests at once gets several 401s, and location.reload() does not
// stop the code that follows it.
let memoryStamp = 0;

function readStamp(): number {
	let stored = 0;
	try {
		const raw = globalThis.localStorage?.getItem(COOLDOWN_KEY);
		const n = raw == null ? NaN : Number(raw);
		if (Number.isFinite(n)) stored = n;
	} catch {
		// Storage disabled (private mode, blocked cookies). We lose the
		// across-reload half of the cooldown and keep the in-memory half.
	}
	return Math.max(memoryStamp, stored);
}

function writeStamp(at: number): void {
	memoryStamp = at;
	try {
		globalThis.localStorage?.setItem(COOLDOWN_KEY, String(at));
	} catch {
		/* see readStamp */
	}
}

/**
 * Reload the page so a forward-auth proxy can redirect us to its login portal.
 *
 * Rate-limited to once per 30s: if the reload doesn't recover the session —
 * misconfigured proxy, or a 401 that means something else entirely — we must
 * not put the tab in a reload loop. Returns whether a reload was started.
 */
export function recoverFromUnauthorized(): boolean {
	if (typeof globalThis.location === 'undefined') return false; // SSR / prerender

	const now = Date.now();
	const last = readStamp();
	// `last > now` means the clock moved backwards or the stamp is junk; treat
	// that as "no recent reload" rather than locking recovery out until it
	// catches up.
	if (last <= now && now - last < COOLDOWN_MS) return false;

	writeStamp(now);
	globalThis.location.reload();
	return true;
}

/**
 * Route a 401 to whichever recovery can actually work.
 *
 * `WWW-Authenticate: Bearer` means Spoolman itself is asking, so we prompt and
 * return without reloading — and without stamping the cooldown, since no reload
 * was spent. Reloading here would be the #406 bug: a tab that reloads every 30s
 * forever and never asks for the credential it is missing.
 *
 * Anything else is the proxy case, where a reload is the fix, subject to
 * `mayReload` — a rejected write keeps its 401 as an ordinary error so the user
 * does not lose what they typed.
 */
export function handleUnauthorized(res: Response, mayReload: boolean): void {
	if (/bearer/i.test(res.headers.get('www-authenticate') ?? '')) {
		requireCredentials();
		return;
	}
	if (mayReload) recoverFromUnauthorized();
}
