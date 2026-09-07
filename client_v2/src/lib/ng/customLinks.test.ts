import { describe, expect, it } from 'vitest';
import type { Spool } from '$lib/types';
import { buildSpoolActionUrl, parseCustomLinks, validateLink } from './customLinks';

// Only the fields a template can name matter; the rest is filler to satisfy the type.
const spool = {
	id: 42,
	filamentId: '7',
	location: 'Shelf A/2',
	lot: 'L-2024 01',
	comment: 'has & ampersand',
	unused: false,
	remaining: 500,
	initial: 1000,
	usedWeight: 500,
	firstUsedLabel: '',
	lastUsedLabel: '',
	registeredLabel: '',
	archived: false,
	tags: [],
	extra: {}
} as unknown as Spool;

describe('parseCustomLinks', () => {
	it('reads the shape both clients store', () => {
		expect(parseCustomLinks('[{"name":"Mainsail","url":"http://mainsail.local"}]')).toEqual([
			{ name: 'Mainsail', url: 'http://mainsail.local' }
		]);
	});

	it('drops what it cannot use instead of throwing', () => {
		expect(parseCustomLinks(undefined)).toEqual([]);
		expect(parseCustomLinks('')).toEqual([]);
		expect(parseCustomLinks('not json')).toEqual([]);
		expect(parseCustomLinks('{"name":"x","url":"y"}')).toEqual([]);
		expect(
			parseCustomLinks('[{"name":"ok","url":"u"},{"name":"no url"},null,7,{"name":1,"url":"u"}]')
		).toEqual([{ name: 'ok', url: 'u' }]);
	});

	it('keeps only the two fields, so a stray key never round-trips back to the server', () => {
		expect(parseCustomLinks('[{"name":"a","url":"b","extra":true}]')).toEqual([{ name: 'a', url: 'b' }]);
	});
});

describe('buildSpoolActionUrl', () => {
	// The same vectors the React client pins (client/src/utils/spoolActionLinks.test.ts), so a
	// link written for one client opens the same address from the other.
	it('substitutes every documented token, URL-encoded', () => {
		expect(
			buildSpoolActionUrl('http://x/{id}/{filament_id}?l={location}&n={lot_nr}&c={comment}', spool)
		).toBe('http://x/42/7?l=Shelf%20A%2F2&n=L-2024%2001&c=has%20%26%20ampersand');
	});

	it('leaves a template without tokens alone', () => {
		expect(buildSpoolActionUrl('http://moonraker.local/server/spoolman/spool_id', spool)).toBe(
			'http://moonraker.local/server/spoolman/spool_id'
		);
	});

	it('turns an unknown token into nothing rather than a literal brace', () => {
		expect(buildSpoolActionUrl('http://x/?id={id}&typo={spool_id}', spool)).toBe('http://x/?id=42&typo=');
	});

	it('turns an empty field into nothing', () => {
		const bare = { ...spool, location: '', lot: '', comment: '' } as Spool;
		expect(buildSpoolActionUrl('http://x/?l={location}&n={lot_nr}&c={comment}', bare)).toBe(
			'http://x/?l=&n=&c='
		);
	});
});

describe('validateLink', () => {
	it('requires both fields and enforces the React form limits', () => {
		expect(validateLink('a', 'b')).toBeNull();
		expect(validateLink('  ', 'b')).toBe('name');
		expect(validateLink('a', '')).toBe('url');
		expect(validateLink('x'.repeat(128), 'b')).toBeNull();
		expect(validateLink('x'.repeat(129), 'b')).toBe('name');
		expect(validateLink('a', 'y'.repeat(513))).toBe('url');
	});
});
