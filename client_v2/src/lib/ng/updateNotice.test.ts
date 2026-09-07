import { describe, expect, it } from 'vitest';
import { UPDATE_NOTIFIED_KEY, rememberUpdateNotice, shouldShowUpdateNotice } from './updateNotice';

// The once-per-release rule behind the update notice. The interesting cases are all about the
// remembered version: the same one silences the notice, an older one does not, and storage that
// refuses to answer must not silence it either.

function fakeStorage(initial: Record<string, string> = {}): Storage {
	const data = new Map<string, string>(Object.entries(initial));
	return {
		getItem: (k: string) => data.get(k) ?? null,
		setItem: (k: string, v: string) => void data.set(k, v),
		removeItem: (k: string) => void data.delete(k),
		clear: () => data.clear(),
		key: () => null,
		get length() {
			return data.size;
		}
	} as Storage;
}

/** Storage that throws on every access, as a browser in private mode can. */
const throwingStorage = () =>
	({
		getItem: () => {
			throw new Error('storage disabled');
		},
		setItem: () => {
			throw new Error('storage disabled');
		}
	}) as unknown as Storage;

describe('shouldShowUpdateNotice', () => {
	it('says nothing when the server reports no update', () => {
		expect(shouldShowUpdateNotice({ updateAvailable: false, latestVersion: null }, fakeStorage())).toBe(
			false
		);
	});

	it('says nothing when an update is reported without a version to name', () => {
		expect(shouldShowUpdateNotice({ updateAvailable: true, latestVersion: null }, fakeStorage())).toBe(false);
	});

	it('shows an update nobody has been told about', () => {
		expect(shouldShowUpdateNotice({ updateAvailable: true, latestVersion: '1.2.3' }, fakeStorage())).toBe(
			true
		);
	});

	it('stays quiet about the version already dismissed', () => {
		const storage = fakeStorage({ [UPDATE_NOTIFIED_KEY]: '1.2.3' });
		expect(shouldShowUpdateNotice({ updateAvailable: true, latestVersion: '1.2.3' }, storage)).toBe(false);
	});

	it('speaks up again when a newer version than the dismissed one ships', () => {
		const storage = fakeStorage({ [UPDATE_NOTIFIED_KEY]: '1.2.3' });
		expect(shouldShowUpdateNotice({ updateAvailable: true, latestVersion: '1.3.0' }, storage)).toBe(true);
	});

	it('shows the notice when storage cannot be read at all', () => {
		expect(shouldShowUpdateNotice({ updateAvailable: true, latestVersion: '1.2.3' }, throwingStorage())).toBe(
			true
		);
	});

	it('shows the notice when there is no storage object at all', () => {
		expect(shouldShowUpdateNotice({ updateAvailable: true, latestVersion: '1.2.3' }, undefined)).toBe(true);
	});
});

describe('rememberUpdateNotice', () => {
	it('records the version, which is what silences the notice', () => {
		const storage = fakeStorage();
		rememberUpdateNotice('1.2.3', storage);
		expect(storage.getItem(UPDATE_NOTIFIED_KEY)).toBe('1.2.3');
		expect(shouldShowUpdateNotice({ updateAvailable: true, latestVersion: '1.2.3' }, storage)).toBe(false);
	});

	it('does not throw when storage refuses the write', () => {
		expect(() => rememberUpdateNotice('1.2.3', throwingStorage())).not.toThrow();
		expect(() => rememberUpdateNotice('1.2.3', undefined)).not.toThrow();
	});
});

describe('the storage key', () => {
	it('is shared with the React client, so switching interface does not re-announce a dismissed release', () => {
		expect(UPDATE_NOTIFIED_KEY).toBe('spoolman-update-notified');
	});
});
