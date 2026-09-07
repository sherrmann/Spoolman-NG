/**
 * User-configured links (#92, #140): extra entries in the nav, and per-spool action buttons.
 *
 * Both live in server settings as a JSON array of `{ name, url }` -- the same shape the React
 * client reads and writes (client/src/utils/customLinks.ts), so the two clients share one
 * list. The backend validates only that the value is a list, so parsing is deliberately
 * forgiving: a malformed entry is dropped rather than taking the nav down with it.
 *
 * Only the spool-action URLs are templates. `{id}` and friends are replaced per spool, values
 * URL-encoded, and an unknown or empty token becomes nothing at all -- a typo in a template
 * yields a harmless truncated URL rather than a literal brace in the address bar.
 */
import type { Spool } from '$lib/types';

export interface CustomLink {
	name: string;
	url: string;
}

export const NAME_MAX = 128;
export const URL_MAX = 512;

export function parseCustomLinks(value: string | undefined): CustomLink[] {
	try {
		const parsed: unknown = JSON.parse(value ?? '[]');
		if (!Array.isArray(parsed)) return [];
		return parsed
			.filter(
				(l): l is CustomLink =>
					!!l && typeof l === 'object' && typeof l.name === 'string' && typeof l.url === 'string'
			)
			.map((l) => ({ name: l.name, url: l.url }));
	} catch {
		return [];
	}
}

/** The fields a template may name, from the spool as this client holds it. */
function tokens(spool: Spool): Record<string, string | number | undefined> {
	return {
		id: spool.id,
		filament_id: spool.filamentId,
		location: spool.location,
		lot_nr: spool.lot,
		comment: spool.comment
	};
}

export function buildSpoolActionUrl(template: string, spool: Spool): string {
	const values = tokens(spool);
	return template.replace(/\{(\w+)\}/g, (_match, key: string) => {
		const value = values[key];
		return value === undefined || value === null || value === '' ? '' : encodeURIComponent(String(value));
	});
}

/** Both fields are required; the limits are the React form's. Returns the failing field. */
export function validateLink(name: string, url: string): 'name' | 'url' | null {
	const n = name.trim();
	const u = url.trim();
	if (!n || n.length > NAME_MAX) return 'name';
	if (!u || u.length > URL_MAX) return 'url';
	return null;
}
