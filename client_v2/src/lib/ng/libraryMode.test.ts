import { describe, expect, it } from 'vitest';
import { parseStoredMode } from './libraryMode';

describe('parseStoredMode', () => {
	it('reads back the gallery', () => {
		expect(parseStoredMode('gallery')).toBe('gallery');
	});

	it('falls back to the list for anything else', () => {
		// Nothing stored, a value from some other build, or a hand-edited entry: the layout the
		// Library ships with is always a safe answer.
		for (const raw of [null, '', 'list', 'grid', 'Gallery', '"gallery"']) {
			expect(parseStoredMode(raw)).toBe('list');
		}
	});
});
