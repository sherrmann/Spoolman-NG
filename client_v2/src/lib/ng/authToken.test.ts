import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The credential module, and in particular the websocket half of it. A browser
// cannot set an Authorization header on a WS handshake, so a token that only
// ever reached the REST calls would leave live updates and the scan relay
// refused with close code 4401 while the rest of the app looked fine.

function fakeStorage(): Storage {
	const data = new Map<string, string>();
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

async function load() {
	vi.resetModules();
	return import('./authToken');
}

beforeEach(() => vi.stubGlobal('localStorage', fakeStorage()));
afterEach(() => vi.unstubAllGlobals());

describe('storage', () => {
	it('round-trips a token', async () => {
		const { getToken, setToken } = await load();
		expect(getToken()).toBeNull();
		setToken('abc');
		expect(getToken()).toBe('abc');
	});

	it('shares the key with the other client, so switching interface keeps you signed in', async () => {
		const { setToken } = await load();
		setToken('abc');
		expect(localStorage.getItem('spoolmanApiToken')).toBe('abc');
	});

	it('clears', async () => {
		const { clearToken, getToken, setToken } = await load();
		setToken('abc');
		clearToken();
		expect(getToken()).toBeNull();
	});

	it('still serves the token for this tab when storage is unavailable', async () => {
		vi.stubGlobal('localStorage', {
			getItem: () => {
				throw new Error('storage disabled');
			},
			setItem: () => {
				throw new Error('storage disabled');
			},
			removeItem: () => {
				throw new Error('storage disabled');
			}
		});
		const { getToken, setToken } = await load();
		setToken('abc');
		expect(getToken()).toBe('abc');
	});
});

describe('authHeaders', () => {
	it('is empty with no token, so no header is sent at all', async () => {
		const { authHeaders } = await load();
		expect(authHeaders()).toEqual({});
	});

	it('carries the bearer scheme the server expects', async () => {
		const { authHeaders, setToken } = await load();
		setToken('abc');
		expect(authHeaders()).toEqual({ Authorization: 'Bearer abc' });
	});
});

describe('withWsToken', () => {
	it('leaves the URL alone with no token', async () => {
		const { withWsToken } = await load();
		expect(withWsToken('ws://h/api/v1/spool')).toBe('ws://h/api/v1/spool');
	});

	it('appends the token as the first query parameter', async () => {
		const { setToken, withWsToken } = await load();
		setToken('abc');
		expect(withWsToken('ws://h/api/v1/spool')).toBe('ws://h/api/v1/spool?token=abc');
	});

	it('joins onto a query string that is already there', async () => {
		const { setToken, withWsToken } = await load();
		setToken('abc');
		expect(withWsToken('ws://h/api/v1/spool?a=1')).toBe('ws://h/api/v1/spool?a=1&token=abc');
	});

	it('encodes a token that would otherwise break the URL', async () => {
		const { setToken, withWsToken } = await load();
		setToken('a b&c=d');
		expect(withWsToken('ws://h/x')).toBe('ws://h/x?token=a%20b%26c%3Dd');
	});
});

describe('credential prompt', () => {
	it('reaches the registered listener', async () => {
		const { onCredentialsRequired, requireCredentials } = await load();
		const prompt = vi.fn();
		onCredentialsRequired(prompt);
		requireCredentials();
		expect(prompt).toHaveBeenCalledTimes(1);
	});

	it('is a no-op before the shell has registered one', async () => {
		const { requireCredentials } = await load();
		expect(() => requireCredentials()).not.toThrow();
	});

	it('stops calling a disposed listener', async () => {
		const { onCredentialsRequired, requireCredentials } = await load();
		const prompt = vi.fn();
		onCredentialsRequired(prompt)();
		requireCredentials();
		expect(prompt).not.toHaveBeenCalled();
	});
});
