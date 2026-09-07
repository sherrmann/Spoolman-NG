import { describe, expect, it } from 'vitest';
import { VIEW_STATE_KEYS, clearPersistedViewState } from './viewState';

// The error page's reset action. What is being tested is not really the loop -- it is the
// *membership* of the list, because the damage a too-broad reset does is silent: the user presses
// a button offered as "reset view settings" and loses their theme, their scanner pairing or their
// low-stock threshold, and nothing tells them that is what happened.

function fakeStorage(seed: Record<string, string> = {}): Storage {
	const data = new Map<string, string>(Object.entries(seed));
	return {
		getItem: (k: string) => data.get(k) ?? null,
		setItem: (k: string, v: string) => void data.set(k, v),
		removeItem: (k: string) => void data.delete(k),
		clear: () => data.clear(),
		key: (i: number) => [...data.keys()][i] ?? null,
		get length() {
			return data.size;
		}
	} as Storage;
}

/**
 * Stored values that are NOT view state and must come through a reset untouched.
 *
 * The credential and the locale because losing them signs the user out and changes the language
 * of the very page explaining what went wrong; the theme, the low-stock threshold, the scanner
 * pairing, the search threshold, the adjust mode and the print-checklist opt-out because they are
 * preferences someone set once and would have to hunt for again; `spoolman.auth-reload-at`
 * because it exists to stop a 401 reload loop, and clearing it from a page whose action is a
 * reload is precisely the wrong moment. The last two here landed with the checklist (#296) and
 * the update notice (#293) after the allowlist was drawn up, and are the reason it is a list.
 */
const SURVIVORS = [
	'spoolmanApiToken',
	'PARAGLIDE_LOCALE',
	'spoolman-v2-theme',
	'spoolman-v2-low-threshold',
	'spoolman-v2-scanner-reader',
	'spoolman-v2-scanner-auto-navigate',
	'spoolman-search-threshold',
	'spoolman-v2-adjust-mode',
	'spoolman.auth-reload-at',
	'spoolman-v2-skip-print-checklist',
	'spoolman-update-notified'
];

describe('VIEW_STATE_KEYS', () => {
	// Pinned as a whole list rather than checked for membership: growing or shrinking what a
	// reset destroys has to be a deliberate edit to this file, not a side effect of touching
	// viewState.ts.
	it('is exactly the four view-state keys, each matching its owner module', () => {
		expect([...VIEW_STATE_KEYS]).toEqual([
			'spoolman-v2-library-view',
			'spoolman-v2-dashboard-field',
			'spoolman-v2-collapsed-groups',
			'spoolman-v2-list-width'
		]);
	});
});

describe('clearPersistedViewState', () => {
	it('removes the view state and leaves every other stored value alone', () => {
		const seed: Record<string, string> = {};
		for (const key of [...VIEW_STATE_KEYS, ...SURVIVORS]) seed[key] = `value-of-${key}`;
		const storage = fakeStorage(seed);

		clearPersistedViewState(storage);

		for (const key of VIEW_STATE_KEYS) expect(storage.getItem(key)).toBeNull();
		for (const key of SURVIVORS) expect(storage.getItem(key)).toBe(`value-of-${key}`);
		expect(storage.length).toBe(SURVIVORS.length);
	});

	it('is a no-op on storage that holds none of them', () => {
		const storage = fakeStorage({ 'spoolman-v2-theme': 'dark' });
		expect(() => clearPersistedViewState(storage)).not.toThrow();
		expect(storage.getItem('spoolman-v2-theme')).toBe('dark');
	});

	// The reset button reloads immediately afterwards, and a throw here would stop that -- the
	// recovery would fail on exactly the browsers (private mode, site data blocked) where the
	// stored value cannot be the problem in the first place.
	it('survives storage that throws on access', () => {
		const hostile = {
			getItem: () => {
				throw new Error('storage disabled');
			},
			setItem: () => {
				throw new Error('storage disabled');
			},
			removeItem: () => {
				throw new Error('storage disabled');
			}
		} as unknown as Storage;
		expect(() => clearPersistedViewState(hostile)).not.toThrow();
	});

	it('survives no storage at all', () => {
		expect(() => clearPersistedViewState(undefined)).not.toThrow();
	});
});
