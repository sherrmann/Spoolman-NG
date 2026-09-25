/**
 * How the Library lays out its spools: rows, or a gallery of cards (#412 step 3).
 *
 * A layout preference, like the list's width or which groups are collapsed, so it lives in
 * localStorage rather than in the URL. Putting it in the URL would mean editing upstream's
 * params.ts and would make every shared link carry the sender's layout.
 */
export type LibraryMode = 'list' | 'gallery';

export const LIBRARY_MODE_KEY = 'spoolman-ng-library-mode';

/** A stored mode, or the list for anything else: nothing stored, junk, a mode since removed. */
export function parseStoredMode(raw: string | null): LibraryMode {
	return raw === 'gallery' ? 'gallery' : 'list';
}
