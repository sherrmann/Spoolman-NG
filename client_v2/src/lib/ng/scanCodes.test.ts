import { describe, it, expect } from 'vitest';
import { CLEAR_PAYLOAD, isClearScan, looksLikeRetailBarcode } from './scanCodes';
import { parseSpoolCode } from '$lib/utils/spoolCode';

describe('the clear sentinel', () => {
	it('recognises the reserved payload', () => {
		expect(isClearScan(CLEAR_PAYLOAD)).toBe(true);
	});

	it('is case- and whitespace-insensitive, like a scanner emits it', () => {
		expect(isClearScan('web+spoolman:clear')).toBe(true);
		expect(isClearScan('  WEB+SPOOLMAN:Clear \n')).toBe(true);
	});

	it('does not swallow an entity code that merely starts the same', () => {
		expect(isClearScan('WEB+SPOOLMAN:S-1')).toBe(false);
		expect(isClearScan('WEB+SPOOLMAN:CLEARANCE')).toBe(false);
	});

	it('is not itself parseable as an entity, so the two never collide', () => {
		// Both paths see every scan; if the sentinel also parsed as a spool the scanner would
		// navigate somewhere instead of clearing.
		expect(parseSpoolCode(CLEAR_PAYLOAD)).toBeNull();
	});
});

describe('retail barcodes', () => {
	it('accepts the four lengths retail codes come in', () => {
		expect(looksLikeRetailBarcode('12345678')).toBe(true); // EAN-8
		expect(looksLikeRetailBarcode('123456789012')).toBe(true); // UPC-A
		expect(looksLikeRetailBarcode('1234567890123')).toBe(true); // EAN-13
		expect(looksLikeRetailBarcode('12345678901234')).toBe(true); // GTIN-14
	});

	it('rejects digit strings of other lengths', () => {
		expect(looksLikeRetailBarcode('1234567')).toBe(false);
		expect(looksLikeRetailBarcode('1234567890')).toBe(false);
		expect(looksLikeRetailBarcode('123456789012345')).toBe(false);
	});

	it('rejects anything that is not all digits', () => {
		expect(looksLikeRetailBarcode('1234-5678')).toBe(false);
		expect(looksLikeRetailBarcode('ABCDEFGH')).toBe(false);
		expect(looksLikeRetailBarcode('')).toBe(false);
	});

	it('tolerates the whitespace a scanner appends', () => {
		expect(looksLikeRetailBarcode(' 1234567890123\n')).toBe(true);
	});

	it('never claims a Spoolman code', () => {
		// The retail path is only consulted for scans spoolCode rejected, but an overlap would
		// send an entity scan off to an article-number lookup, so it is worth pinning.
		for (const code of ['WEB+SPOOLMAN:S-12345678', 'https://x.test/spool/show/12345678']) {
			expect(looksLikeRetailBarcode(code)).toBe(false);
		}
	});
});
