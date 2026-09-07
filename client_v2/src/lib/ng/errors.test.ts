import { describe, expect, it } from 'vitest';
import { HttpError } from '$lib/api/http';
import { apiErrorMessage } from './errors';

describe('apiErrorMessage', () => {
	it('reads the /auth dialect', () => {
		const e = new HttpError('DELETE /auth/users/3 → 400', 400, {
			detail: 'Cannot delete the last administrator.'
		});
		expect(apiErrorMessage(e)).toBe('Cannot delete the last administrator.');
	});

	it('reads the Message dialect everything else speaks', () => {
		const e = new HttpError('POST /printer → 400', 400, { message: 'Extra field x is invalid' });
		expect(apiErrorMessage(e)).toBe('Extra field x is invalid');
	});

	it('prefers detail when a body somehow carries both', () => {
		const e = new HttpError('x', 400, { detail: 'one', message: 'two' });
		expect(apiErrorMessage(e)).toBe('one');
	});

	it('falls back to the transport message, then to the caller fallback', () => {
		expect(apiErrorMessage(new HttpError('GET /x → 500', 500))).toBe('GET /x → 500');
		expect(apiErrorMessage(new HttpError('GET /x → 500', 500), 'Request failed')).toBe('Request failed');
		expect(apiErrorMessage(new Error('boom'))).toBe('boom');
		expect(apiErrorMessage('not an error', 'Request failed')).toBe('Request failed');
		expect(apiErrorMessage(undefined)).toBe('');
	});
});
