// Spoolman NG fork addition. The root that link-form QR codes are built from.
//
// A non-empty Base URL setting wins. Otherwise the fallback is the page origin plus the base
// path, so a sub-path deploy (SPOOLMAN_BASE_PATH=/spoolman) yields https://host/spoolman/...
// and not a link that misses the app. Home Assistant ingress is the exception: its base path
// (/api/hassio_ingress/<token>) carries a rotating per-session token that must not be printed
// into a code, so there the fallback stays the bare origin. client_v2 does not load
// /config.js and so has no ingress flag; the path shape is the only signal it has.

import { resolve } from '$app/paths';

const HA_INGRESS_PATH = /^\/api\/hassio_ingress(\/|$)/;

function trimSlashes(s: string): string {
	return s.replace(/\/+$/, '');
}

/** Link root for the given Base URL setting value, without a trailing slash. */
export function linkRoot(baseUrl: string): string {
	if (baseUrl) return trimSlashes(baseUrl);
	if (typeof window === 'undefined') return '';
	const basePath = trimSlashes(resolve('/'));
	return window.location.origin + (HA_INGRESS_PATH.test(basePath) ? '' : basePath);
}
