/**
 * The persisted view state an error page is allowed to throw away (#417).
 *
 * A page that will not render is usually a page that has been handed something it cannot make
 * sense of, and the likeliest source of that in a client-side app is a value it stored itself on
 * an earlier visit -- the shape that white-screened the React client in #44. So the error page
 * offers one recovery action: forget how the views were last laid out, and reload.
 *
 * This is an ALLOWLIST of four literals, not a `spoolman-v2-` prefix sweep, and that distinction
 * is the whole point of the module. The same prefix also carries the theme, the low-stock
 * threshold, the scanner pairing and the last-used adjust mode; a sweep would sign the user out
 * of their own preferences to fix a collapsed group. What is listed here is only ever "how a view
 * was arranged", which the app rebuilds from its defaults on the next paint and which the user
 * can set again in seconds.
 *
 * Honest about what this is: every one of the four already validates what it reads
 * (`library/viewPrefs`, `stores/collapsedGroups`, `stores/listWidth` and `dashboard/params` all
 * parse defensively and fall back), so there is no crash today that this fixes. It is parity with
 * the React client's boundary, and insurance for persisted state added later that is less careful.
 *
 * Deliberately free of imports: this is called from the very page that renders when something
 * else has already failed, and reaching for a store here would run that store's module-level read
 * of the suspect value inside the recovery path.
 */

/**
 * Everything a "reset view settings" removes, and nothing else.
 *
 * Each entry names the module that owns it. Adding a key here means claiming it is safe to lose
 * without the user noticing anything but a view returning to its default.
 */
export const VIEW_STATE_KEYS = [
	// library/viewPrefs.ts -- the Library's remembered grouping, sort and show-empty toggle.
	'spoolman-v2-library-view',
	// dashboard/params.ts -- the field the dashboard was last grouped by.
	'spoolman-v2-dashboard-field',
	// stores/collapsedGroups.svelte.ts -- which Library groups are shut.
	'spoolman-v2-collapsed-groups',
	// stores/listWidth.svelte.ts -- how wide the Library's list column is.
	'spoolman-v2-list-width'
] as const;

/**
 * Remove the view state, leaving every other stored value alone.
 *
 * Storage may be absent (never on the server here, since SSR is off, but a caller can pass
 * `undefined`) and may throw on access in private browsing or with site data blocked. Neither can
 * be allowed to fail the reset: the reload that follows is the larger half of the recovery, and it
 * happens either way.
 */
export function clearPersistedViewState(storage: Storage | undefined): void {
	try {
		for (const key of VIEW_STATE_KEYS) storage?.removeItem(key);
	} catch {
		/* storage unavailable -- the reload still happens */
	}
}
