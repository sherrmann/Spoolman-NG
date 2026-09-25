import { describe, expect, it } from 'vitest';
import { defaultSortAsc, isGroupOrderable, resolveSortField, sortDefs } from '$lib/utils/library';

// The library's "ID" sort (upstream issue 1154), a fork addition to FIXED_SORTS.
describe('sorting the library by spool ID', () => {
	it('is offered in the spool section and sent to the backend as `id`', () => {
		expect(sortDefs().find((d) => d.key === 'id')?.section).toBe('spool');
		expect(resolveSortField('id')).toBe('id');
	});

	it('starts ascending, the order labels are numbered in', () => {
		expect(defaultSortAsc('id')).toBe(true);
	});

	it('flattens a grouped view, since groups cannot be ordered by one spool’s ID', () => {
		expect(isGroupOrderable('id', 'filament')).toBe(false);
		expect(isGroupOrderable('id', 'none')).toBe(true);
	});
});
