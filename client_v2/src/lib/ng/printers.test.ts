import { describe, expect, it } from 'vitest';
import { mapPrinter, printerBody, validatePrinter } from './printers';

describe('mapPrinter', () => {
	it('reads a full list row', () => {
		expect(
			mapPrinter({
				id: 3,
				registered: '2026-09-01T10:00:00Z',
				name: 'Voron 2.4',
				comment: 'left bench',
				spool_count: 2,
				extra: { nozzle: '"0.4"' }
			})
		).toEqual({
			id: 3,
			registered: '2026-09-01T10:00:00Z',
			name: 'Voron 2.4',
			comment: 'left bench',
			spoolCount: 2,
			extra: { nozzle: '"0.4"' }
		});
	});

	it('treats an absent field the same as a null one', () => {
		// The API omits nulls (response_model_exclude_none), and a printer nested in a spool
		// never carries the aggregate at all.
		const absent = mapPrinter({ id: 1, name: 'A', extra: {} });
		const nulled = mapPrinter({ id: 1, name: 'A', comment: null, spool_count: null, extra: {} });
		expect(absent).toEqual(nulled);
		expect(absent.comment).toBeUndefined();
		expect(absent.spoolCount).toBeUndefined();
	});

	it('never yields a missing extra map', () => {
		expect(mapPrinter({ id: 1, name: 'A' }).extra).toEqual({});
	});
});

describe('validatePrinter', () => {
	it('requires a name within 64 characters and a comment within 1024', () => {
		expect(validatePrinter('Voron', '')).toBeNull();
		expect(validatePrinter('   ', '')).toBe('name');
		expect(validatePrinter('x'.repeat(64), '')).toBeNull();
		expect(validatePrinter('x'.repeat(65), '')).toBe('name');
		expect(validatePrinter('ok', 'y'.repeat(1024))).toBeNull();
		expect(validatePrinter('ok', 'y'.repeat(1025))).toBe('comment');
	});
});

describe('printerBody', () => {
	it('sends a trimmed name and comment', () => {
		expect(printerBody(' Voron ', ' bench ', false)).toEqual({ name: 'Voron', comment: 'bench' });
	});

	it('clears a comment with an explicit null only when editing', () => {
		// PATCH ignores absent keys, so an emptied comment must be sent as null to take effect;
		// POST has nothing to clear and stays minimal.
		expect(printerBody('Voron', '', true)).toEqual({ name: 'Voron', comment: null });
		expect(printerBody('Voron', '', false)).toEqual({ name: 'Voron' });
	});
});
