import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/api/http', () => ({
	getJson: vi.fn(),
	HttpError: class HttpError extends Error {
		constructor(
			message: string,
			readonly status: number,
			readonly body?: Record<string, unknown>
		) {
			super(message);
		}
	}
}));

const { getJson, HttpError } = await import('$lib/api/http');
const { whoAmI, currentUserIsAdmin, resetWhoAmI } = await import('./me');
const mockGetJson = vi.mocked(getJson);

beforeEach(() => {
	resetWhoAmI();
	mockGetJson.mockReset();
});

describe('whoAmI', () => {
	it('asks the server once, however many panels ask', async () => {
		mockGetJson.mockResolvedValue({ id: 0, username: 'alice', role: 'admin' });
		const [a, b, c] = await Promise.all([whoAmI(), whoAmI(), currentUserIsAdmin()]);
		expect(a).toEqual({ username: 'alice', role: 'admin' });
		expect(b).toEqual(a);
		expect(c).toBe(true);
		expect(mockGetJson).toHaveBeenCalledTimes(1);
	});

	it('is nobody when the server wants credentials', async () => {
		mockGetJson.mockRejectedValue(new HttpError('GET /auth/me → 401', 401));
		expect(await whoAmI()).toBeNull();
		expect(await currentUserIsAdmin()).toBe(false);
	});

	it('is a read-only user when the server says so', async () => {
		mockGetJson.mockResolvedValue({ id: 0, username: 'bob', role: 'readonly' });
		expect(await currentUserIsAdmin()).toBe(false);
	});

	it('assumes the anonymous administrator when the backend cannot answer at all', async () => {
		// A server too old to have the route, or one that is down: hiding the panel would
		// hide the problem. The backend itself answers this way with authentication off.
		mockGetJson.mockRejectedValue(new HttpError('GET /auth/me → 404', 404));
		expect(await whoAmI()).toEqual({ username: 'anonymous', role: 'admin' });
	});
});
