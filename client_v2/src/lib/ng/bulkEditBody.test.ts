import { describe, expect, it } from 'vitest';
import { bulkEditBody, type BulkEditForm } from './bulkEditBody';
import { spoolPatchToApi } from '$lib/api/map';

function form(
	ticked: Partial<BulkEditForm['ticked']>,
	values: Partial<BulkEditForm['values']> = {}
): BulkEditForm {
	return {
		ticked: { location: false, lot: false, price: false, comment: false, ...ticked },
		values: { location: '', lot: '', price: '', comment: '', ...values }
	};
}

describe('bulkEditBody', () => {
	it('asks for a tick when nothing is ticked, whatever is typed', () => {
		expect(bulkEditBody(form({}, { location: 'Shelf A' }))).toEqual({ error: 'nothing' });
	});

	it('leaves unticked fields out of the patch', () => {
		const body = bulkEditBody(form({ location: true }, { location: ' Shelf A ', lot: 'L1' }));
		expect(body).toEqual({ patch: { location: 'Shelf A' } });
	});

	it('clears a ticked field left empty', () => {
		const body = bulkEditBody(form({ location: true, lot: true, comment: true, price: true }));
		expect('patch' in body && spoolPatchToApi(body.patch)).toEqual({
			location: '',
			lot_nr: '',
			comment: '',
			// null hands the price back to the filament's.
			price: null
		});
	});

	it('treats a price of 0 as a price, not as a clear', () => {
		const body = bulkEditBody(form({ price: true }, { price: '0' }));
		expect('patch' in body && spoolPatchToApi(body.patch)).toEqual({ price: 0 });
	});

	it('reads a decimal comma', () => {
		expect(bulkEditBody(form({ price: true }, { price: '19,99' }))).toEqual({ patch: { price: 19.99 } });
	});

	it('refuses a price that is not a non-negative number', () => {
		for (const price of ['abc', '-1', 'Infinity']) {
			expect(bulkEditBody(form({ price: true }, { price }))).toEqual({ error: 'price' });
		}
	});
});
