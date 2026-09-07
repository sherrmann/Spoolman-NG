import { describe, expect, it } from 'vitest';
import { isRole, isSelf, validateNewUser } from './users';

describe('validateNewUser', () => {
	it('requires both fields', () => {
		expect(validateNewUser('alice', 'pw')).toBeNull();
		expect(validateNewUser('  ', 'pw')).toBe('username');
		expect(validateNewUser('alice', '')).toBe('password');
	});

	it('keeps the username within the column the backend enforces', () => {
		expect(validateNewUser('x'.repeat(64), 'pw')).toBeNull();
		expect(validateNewUser('x'.repeat(65), 'pw')).toBe('username');
	});
});

describe('isRole', () => {
	it('accepts only the two roles the backend knows', () => {
		expect(isRole('admin')).toBe(true);
		expect(isRole('readonly')).toBe(true);
		expect(isRole('root')).toBe(false);
		expect(isRole('')).toBe(false);
	});
});

describe('isSelf', () => {
	const alice = { id: 3, username: 'alice', role: 'admin' };

	it('matches by username, the only handle /auth/me gives', () => {
		expect(isSelf({ username: 'alice', role: 'admin' }, alice)).toBe(true);
		expect(isSelf({ username: 'bob', role: 'admin' }, alice)).toBe(false);
	});

	it('matches nobody when there is no signed-in account', () => {
		expect(isSelf(null, alice)).toBe(false);
		expect(isSelf({ username: 'alice', role: '' }, alice)).toBe(false);
	});
});
