import { describe, expect, it } from 'vitest';
import { planNlSearch } from './nlSearch';

/**
 * Most of these are about what this client CANNOT express. The server translates language into
 * a shape richer than the Library's filter model, and the failure worth guarding against is not
 * a wrong filter -- it is a search that quietly arrives half applied and looks like a bad match.
 */
describe('planNlSearch', () => {
	it('maps the server field names onto the Library chip props', () => {
		// The two sides genuinely differ, and nothing else in the client knows both spellings.
		const plan = planNlSearch({
			filters: [
				{ field: 'filament.material', values: ['PETG'] },
				{ field: 'filament.vendor.name', values: ['Prusa'] },
				{ field: 'location', values: ['Shelf B'] },
				{ field: 'lot_nr', values: ['A7'] }
			]
		});
		expect(plan.filters).toEqual([
			{ prop: 'material', value: 'PETG' },
			{ prop: 'vendor', value: 'Prusa' },
			{ prop: 'location', value: 'Shelf B' },
			{ prop: 'lot', value: 'A7' }
		]);
		expect(plan.unapplied).toEqual([]);
	});

	it('expands several values on one field into one chip each', () => {
		// The Library models a multi-value filter as repeated chips, not one chip holding a list.
		const plan = planNlSearch({ filters: [{ field: 'filament.material', values: ['PLA', 'PETG'] }] });
		expect(plan.filters).toEqual([
			{ prop: 'material', value: 'PLA' },
			{ prop: 'material', value: 'PETG' }
		]);
	});

	it('reports leftover free text as unapplied rather than dropping it', () => {
		// This client's spool list takes no free-text parameter at all. Saying so is the whole
		// point: a user who asked for "matte black PETG" and got every PETG needs to know why.
		const plan = planNlSearch({
			filters: [{ field: 'filament.material', values: ['PETG'] }],
			search: 'matte'
		});
		expect(plan.filters).toEqual([{ prop: 'material', value: 'PETG' }]);
		expect(plan.unapplied).toContain('search');
	});

	it('reports a colour as unapplied, since there is no colour filter here', () => {
		const plan = planNlSearch({ filters: [], color_hex: '000000' });
		expect(plan.unapplied).toContain('color');
	});

	it('does not report whitespace-only free text as something that was lost', () => {
		expect(planNlSearch({ filters: [], search: '   ' }).unapplied).toEqual([]);
	});

	it('applies a sort the Library offers', () => {
		const plan = planNlSearch({
			filters: [],
			sort: { field: 'remaining_weight', direction: 'asc' }
		});
		expect(plan.sortKey).toBe('remaining_weight');
		expect(plan.sortAsc).toBe(true);
	});

	it('reads any direction but "desc" as ascending', () => {
		expect(planNlSearch({ filters: [], sort: { field: 'price' } }).sortAsc).toBe(true);
		expect(planNlSearch({ filters: [], sort: { field: 'price', direction: 'desc' } }).sortAsc).toBe(false);
	});

	it('refuses a sort field the Library does not have, and says so', () => {
		// An unknown key silently falls back to the default sort, so accepting it would reorder
		// the list by something other than what was asked for and look like a bug in the search.
		const plan = planNlSearch({ filters: [], sort: { field: 'made_up_field' } });
		expect(plan.sortKey).toBeUndefined();
		expect(plan.unapplied).toContain('sort');
	});

	it('drops a filter field it cannot map instead of passing it through', () => {
		// A chip the Library cannot label, on a param the API ignores, reads as "no matches".
		const plan = planNlSearch({
			filters: [
				{ field: 'filament.some_new_field', values: ['x'] },
				{ field: 'location', values: ['Shelf A'] }
			]
		});
		expect(plan.filters).toEqual([{ prop: 'location', value: 'Shelf A' }]);
	});

	it('survives a response with nothing in it', () => {
		// translate() degrades to an empty result rather than erroring, so this is a real case.
		expect(planNlSearch({ filters: [] })).toEqual({ filters: [], unapplied: [] });
	});

	it('ignores an empty filter value', () => {
		expect(planNlSearch({ filters: [{ field: 'location', values: [''] }] }).filters).toEqual([]);
	});
});
