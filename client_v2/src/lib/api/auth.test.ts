import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The cooldown is the whole safety story here: without it, a 401 that a reload
// cannot fix turns the tab into a reload loop. These tests run the module fresh
// each time (vi.resetModules) because it keeps an in-memory stamp that would
// otherwise leak between cases.

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
	return (await import('./auth')).recoverFromUnauthorized;
}

let reload: ReturnType<typeof vi.fn>;

beforeEach(() => {
	reload = vi.fn();
	vi.stubGlobal('location', { reload });
	vi.stubGlobal('localStorage', fakeStorage());
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('recoverFromUnauthorized', () => {
	it('reloads the page on the first 401', async () => {
		const recover = await load();
		expect(recover()).toBe(true);
		expect(reload).toHaveBeenCalledTimes(1);
	});

	it('reloads only once for a burst of 401s', async () => {
		const recover = await load();
		// A view firing several requests at once gets several 401s back, and
		// location.reload() does not stop the code that follows it.
		recover();
		expect(recover()).toBe(false);
		expect(recover()).toBe(false);
		expect(reload).toHaveBeenCalledTimes(1);
	});

	it('does not reload again after coming back still unauthenticated', async () => {
		const recover = await load();
		recover();

		// The reload re-runs the app: fresh module, empty in-memory stamp. Only
		// localStorage carries the cooldown across, which is why it is there.
		const afterReload = await load();
		vi.advanceTimersByTime(5_000);
		expect(afterReload()).toBe(false);
		expect(reload).toHaveBeenCalledTimes(1);
	});

	it('allows another attempt once the cooldown has passed', async () => {
		const recover = await load();
		recover();
		vi.advanceTimersByTime(30_001);
		expect(recover()).toBe(true);
		expect(reload).toHaveBeenCalledTimes(2);
	});

	it('still rate-limits when localStorage is unavailable', async () => {
		vi.stubGlobal('localStorage', {
			getItem: () => {
				throw new Error('storage disabled');
			},
			setItem: () => {
				throw new Error('storage disabled');
			}
		});
		const recover = await load();
		expect(recover()).toBe(true);
		expect(recover()).toBe(false);
		expect(reload).toHaveBeenCalledTimes(1);
	});

	it('is not locked out by a future stamp from a clock change', async () => {
		localStorage.setItem('spoolman.auth-reload-at', String(Date.now() + 60 * 60_000));
		const recover = await load();
		expect(recover()).toBe(true);
	});

	it('does nothing when there is no document to reload', async () => {
		vi.stubGlobal('location', undefined);
		const recover = await load();
		expect(recover()).toBe(false);
	});
});

// Which of the two recoveries a 401 gets. Sending a Spoolman 401 down the reload
// path is #406: the tab reloads every 30s forever and never asks for the
// credential it is missing, because no proxy is there to redirect it.

async function loadHandler() {
	vi.resetModules();
	const { handleUnauthorized } = await import('./auth');
	const { onCredentialsRequired } = await import('$lib/ng/authToken');
	const prompt = vi.fn();
	onCredentialsRequired(prompt);
	return { handleUnauthorized, prompt };
}

function unauthorized(wwwAuthenticate?: string): Response {
	return new Response('{"message":"Missing or invalid credentials."}', {
		status: 401,
		headers: wwwAuthenticate ? { 'www-authenticate': wwwAuthenticate } : {}
	});
}

describe('handleUnauthorized', () => {
	it('prompts, and does not reload, when Spoolman itself asks', async () => {
		const { handleUnauthorized, prompt } = await loadHandler();
		handleUnauthorized(unauthorized('Bearer'), true);
		expect(prompt).toHaveBeenCalledTimes(1);
		expect(reload).not.toHaveBeenCalled();
	});

	it('recognises the header however it is spelled or parameterised', async () => {
		const { handleUnauthorized, prompt } = await loadHandler();
		handleUnauthorized(unauthorized('bearer realm="spoolman", charset="UTF-8"'), true);
		expect(prompt).toHaveBeenCalledTimes(1);
		expect(reload).not.toHaveBeenCalled();
	});

	it('leaves the cooldown unspent, since no reload was used', async () => {
		const { handleUnauthorized } = await loadHandler();
		handleUnauthorized(unauthorized('Bearer'), true);
		// A proxy 401 arriving straight afterwards must still get its one reload.
		handleUnauthorized(unauthorized(), true);
		expect(reload).toHaveBeenCalledTimes(1);
	});

	it('reloads for a 401 with no such header, as before', async () => {
		const { handleUnauthorized, prompt } = await loadHandler();
		handleUnauthorized(unauthorized(), true);
		expect(reload).toHaveBeenCalledTimes(1);
		expect(prompt).not.toHaveBeenCalled();
	});

	it('does neither for a write, which keeps its error instead', async () => {
		const { handleUnauthorized, prompt } = await loadHandler();
		handleUnauthorized(unauthorized(), false);
		expect(reload).not.toHaveBeenCalled();
		expect(prompt).not.toHaveBeenCalled();
	});

	it('still prompts on a write, which a reload could never have fixed', async () => {
		const { handleUnauthorized, prompt } = await loadHandler();
		handleUnauthorized(unauthorized('Bearer'), false);
		expect(prompt).toHaveBeenCalledTimes(1);
		expect(reload).not.toHaveBeenCalled();
	});
});
