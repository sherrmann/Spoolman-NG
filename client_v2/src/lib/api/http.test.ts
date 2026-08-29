import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Covers which failures are handed to ./auth.ts, and whether each one is allowed
// to answer with a page reload. The split between reads and writes is the part
// worth pinning down: getting it wrong means a user loses a half-typed form to a
// login redirect.
//
// Note every 401 is now handed over, writes included — only the permission to
// reload differs. A write that 401s still has to be able to raise the credential
// prompt, or an unauthenticated user could only ever be told "save failed".

const { handle } = vi.hoisted(() => ({ handle: vi.fn() }));
vi.mock('./auth', () => ({ handleUnauthorized: handle, recoverFromUnauthorized: vi.fn() }));
vi.mock('./config', () => ({ API_BASE: 'http://spoolman.test/api/v1' }));

/** Whether the Nth handover was told it may reload. */
function mayReload(call = 0): boolean {
	return handle.mock.calls[call]?.[1] as boolean;
}

import { getJson, getList, HttpError, patchJson, postJson, deleteResource } from './http';

function respond(status: number): Response {
	const body = status === 200 ? '[]' : JSON.stringify({ message: 'Unauthorized' });
	return new Response(body, { status, headers: { 'content-type': 'application/json' } });
}

let fetchMock: ReturnType<typeof vi.fn>;

function serving(status: number) {
	fetchMock = vi.fn(async () => respond(status));
	vi.stubGlobal('fetch', fetchMock);
}

beforeEach(() => handle.mockClear());
afterEach(() => vi.unstubAllGlobals());

describe('401 handling', () => {
	it('lets a rejected read answer with a reload', async () => {
		serving(401);
		await expect(getJson('/spool/1')).rejects.toThrow(HttpError);
		expect(handle).toHaveBeenCalledTimes(1);
		expect(mayReload()).toBe(true);
	});

	it('lets a rejected list read answer with a reload', async () => {
		serving(401);
		await expect(getList('/spool')).rejects.toThrow(HttpError);
		expect(handle).toHaveBeenCalledTimes(1);
		expect(mayReload()).toBe(true);
	});

	it('refuses a reload on a rejected write so the user keeps their input', async () => {
		serving(401);
		await expect(patchJson('/spool/1', { comment: 'half typed' })).rejects.toThrow(HttpError);
		await expect(postJson('/spool', {})).rejects.toThrow(HttpError);
		await expect(deleteResource('/spool/1')).rejects.toThrow(HttpError);
		expect(handle).toHaveBeenCalledTimes(3);
		expect([mayReload(0), mayReload(1), mayReload(2)]).toEqual([false, false, false]);
	});

	it('hands the response over, so the caller can read WWW-Authenticate', async () => {
		serving(401);
		await expect(getJson('/spool/1')).rejects.toThrow(HttpError);
		expect(handle.mock.calls[0][0]).toBeInstanceOf(Response);
	});

	it('ignores failures that are not about authentication', async () => {
		serving(500);
		await expect(getJson('/spool/1')).rejects.toThrow(HttpError);
		expect(handle).not.toHaveBeenCalled();
	});

	it('carries the status on the error either way', async () => {
		serving(401);
		await expect(getJson('/spool/1')).rejects.toMatchObject({ status: 401 });
	});

	it('does nothing on a successful read', async () => {
		serving(200);
		await expect(getList('/spool')).resolves.toEqual({ items: [], total: 0 });
		expect(handle).not.toHaveBeenCalled();
	});
});
