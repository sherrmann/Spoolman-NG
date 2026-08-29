import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The regression guard for #406: every wrapper in ./http.ts must carry the
// bearer credential. The client shipped without this, so on an instance with
// SPOOLMAN_API_TOKEN or user accounts every request 401'd and the page reloaded
// on a loop without ever asking for credentials.
//
// Separate file from http.test.ts so the two concerns stay readable: that one
// pins down which failures reach for the reload, this one pins down what goes
// out on the wire.

vi.mock('./auth', () => ({ recoverFromUnauthorized: vi.fn(), handleUnauthorized: vi.fn() }));
vi.mock('./config', () => ({ API_BASE: 'http://spoolman.test/api/v1' }));

import { clearToken, setToken } from '$lib/ng/authToken';
import { deleteJson, deleteResource, getJson, getList, patchJson, postJson, putJson } from './http';

let fetchMock: ReturnType<typeof vi.fn>;

/** The headers the last fetch actually went out with, normalised to lowercase keys. */
function sentHeaders(): Record<string, string> {
	const init = fetchMock.mock.calls.at(-1)?.[1] as RequestInit | undefined;
	const out: Record<string, string> = {};
	for (const [k, v] of Object.entries((init?.headers ?? {}) as Record<string, string>)) {
		out[k.toLowerCase()] = v;
	}
	return out;
}

beforeEach(() => {
	fetchMock = vi.fn(
		async () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
	);
	vi.stubGlobal('fetch', fetchMock);
	clearToken();
});

afterEach(() => {
	clearToken();
	vi.unstubAllGlobals();
});

describe('bearer credential', () => {
	it('is absent when no token is held', async () => {
		await getJson('/spool/1');
		expect(sentHeaders()).not.toHaveProperty('authorization');
	});

	it.each([
		['getJson', () => getJson('/spool/1')],
		['getList', () => getList('/spool')],
		['patchJson', () => patchJson('/spool/1', {})],
		['putJson', () => putJson('/spool/1', {})],
		['postJson', () => postJson('/spool', {})],
		['deleteResource', () => deleteResource('/spool/1')],
		['deleteJson', () => deleteJson('/spool/1')]
	])('is attached by %s', async (_name, call) => {
		setToken('sekrit-406');
		await call();
		expect(sentHeaders()).toMatchObject({ authorization: 'Bearer sekrit-406' });
	});

	it('does not displace the content type a write needs', async () => {
		setToken('sekrit-406');
		await postJson('/spool', {});
		expect(sentHeaders()).toMatchObject({
			authorization: 'Bearer sekrit-406',
			'content-type': 'application/json'
		});
	});
});
