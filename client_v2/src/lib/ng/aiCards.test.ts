import { describe, expect, it } from 'vitest';
import { cardRows, formatCardValue, humaniseKey } from './aiCards';

const NOT_SET = 'not set';

describe('cardRows', () => {
	it('lists what will exist, for a create', () => {
		expect(cardRows({ before: {}, after: { name: 'PLA Black', weight: 1000 } }, NOT_SET)).toEqual([
			{ label: 'Name', before: '', after: 'PLA Black', changed: false },
			{ label: 'Weight', before: '', after: '1,000', changed: false }
		]);
	});

	it('lists what will be lost, for a delete', () => {
		// Shown as plain values rather than as a diff to nothing: "Shelf A → not set" would
		// read as an edit, when the row is really telling you what disappears.
		expect(cardRows({ before: { location: 'Shelf A' }, after: {} }, NOT_SET)).toEqual([
			{ label: 'Location', before: '', after: 'Shelf A', changed: false }
		]);
	});

	it('shows only the fields that actually change, for an update', () => {
		// The server sends whole objects. A card listing every unchanged field around the one
		// that moved hides exactly what it exists to show.
		const rows = cardRows(
			{
				before: { location: 'Shelf A', lot_nr: 'X1', comment: 'keep' },
				after: { location: 'Shelf B', lot_nr: 'X1', comment: 'keep' }
			},
			NOT_SET
		);
		expect(rows).toEqual([{ label: 'Location', before: 'Shelf A', after: 'Shelf B', changed: true }]);
	});

	it('does not report a list as changed just because JSON rebuilt it', () => {
		// Every value arrives as a fresh instance over the wire, so reference equality would
		// mark every object-valued field as edited and bury the real one.
		const rows = cardRows(
			{ before: { colors: ['a', 'b'], name: 'x' }, after: { colors: ['a', 'b'], name: 'y' } },
			NOT_SET
		);
		expect(rows.map((r) => r.label)).toEqual(['Name']);
	});

	it('treats a field being cleared as a change, not as absent', () => {
		// Setting something to empty is a real edit and has to be previewable.
		expect(cardRows({ before: { comment: 'note' }, after: { comment: '' } }, NOT_SET)).toEqual([
			{ label: 'Comment', before: 'note', after: NOT_SET, changed: true }
		]);
	});

	it('shows a field that had no previous value as being set', () => {
		expect(cardRows({ before: { lot_nr: null }, after: { lot_nr: 'A7' } }, NOT_SET)).toEqual([
			{ label: 'Lot nr', before: NOT_SET, after: 'A7', changed: true }
		]);
	});

	it('returns nothing when an update changes nothing', () => {
		expect(cardRows({ before: { a: 1 }, after: { a: 1 } }, NOT_SET)).toEqual([]);
	});
});

describe('formatCardValue', () => {
	it('names an unset value rather than showing an empty cell', () => {
		// A blank cell is ambiguous between "unset" and "the preview failed to render".
		expect(formatCardValue(null, NOT_SET)).toBe(NOT_SET);
		expect(formatCardValue(undefined, NOT_SET)).toBe(NOT_SET);
		expect(formatCardValue('', NOT_SET)).toBe(NOT_SET);
	});

	it('keeps zero, which is a value and not an absence', () => {
		expect(formatCardValue(0, NOT_SET)).toBe('0');
	});

	it('keeps false, likewise', () => {
		expect(formatCardValue(false, NOT_SET)).toBe('✗');
	});

	it('renders a list as its members', () => {
		expect(formatCardValue(['a', 'b'], NOT_SET)).toBe('a, b');
	});
});

describe('humaniseKey', () => {
	it('turns a wire field name into a label', () => {
		expect(humaniseKey('used_weight')).toBe('Used weight');
		expect(humaniseKey('lot-nr')).toBe('Lot nr');
	});
});
