import { describe, expect, it } from 'vitest';
import { buildLinkUrl } from './linkField';

/**
 * The four branches of a link field's URL expansion (#129), plus the encoding of the two
 * characters that decide whether a value stays inside the path segment it was put in: a `/`
 * would otherwise walk up the URL, and an `&` would start a query parameter of its own.
 *
 * These cases are the React client's (`client/src/utils/linkField.test.ts`) with the same
 * expectations, because both clients read the same stored value out of the same field
 * definition and have to arrive at the same URL.
 */
describe('buildLinkUrl', () => {
	it('substitutes the value into a {} placeholder', () => {
		expect(buildLinkUrl('https://www.amazon.com/dp/{}', 'B0ABCDEF')).toBe(
			'https://www.amazon.com/dp/B0ABCDEF'
		);
	});

	it('substitutes into every placeholder occurrence', () => {
		expect(buildLinkUrl('https://example.com/{}?ref={}', 'abc')).toBe('https://example.com/abc?ref=abc');
	});

	it('appends the value when the template has no placeholder', () => {
		expect(buildLinkUrl('https://example.com/part/', '12345')).toBe('https://example.com/part/12345');
	});

	it('returns an empty string for an empty value, so no link is offered', () => {
		expect(buildLinkUrl('https://example.com/{}', '')).toBe('');
	});

	it('encodes a slash so the value cannot escape its path segment', () => {
		expect(buildLinkUrl('https://example.com/{}', 'a b/c')).toBe('https://example.com/a%20b%2Fc');
	});

	it('encodes an ampersand so an appended value cannot start a parameter', () => {
		expect(buildLinkUrl('https://example.com/search?q=', 'PLA & PETG')).toBe(
			'https://example.com/search?q=PLA%20%26%20PETG'
		);
	});
});
