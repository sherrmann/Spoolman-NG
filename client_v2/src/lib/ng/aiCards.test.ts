import { describe, expect, it } from 'vitest';
import { cardRows, formatCardValue, humaniseKey } from './aiCards';
import { resultCard, swatchColour, usageBars, type CardWords } from './aiCards';

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

describe('read-tool result cards (#381)', () => {
	const words: CardWords = {
		spools: (n) => `${n} spools`,
		filaments: (n) => `${n} filaments`,
		outstanding: (n) => `${n} outstanding`,
		arrived: 'Arrived',
		match: (p) => `${p}% match`
	};
	const paths = {
		spool: (id: number) => `/spool/show/${id}`,
		filament: (id: number) => `/filament/show/${id}`
	};

	it('builds spool rows with a swatch, weight and link, and counts what is not shown', () => {
		const card = resultCard(
			'find_spools',
			[
				{
					id: 3,
					filament: 'Acme PLA Black',
					material: 'PLA',
					color_hex: '1B1B1F',
					remaining_weight_g: 1234.5,
					location: 'Shelf A'
				}
			],
			9,
			words,
			paths
		);
		expect(card?.more).toBe(8);
		expect(card?.rows[0]).toMatchObject({
			title: '#3 Acme PLA Black',
			detail: 'PLA · Shelf A',
			swatch: '#1B1B1F',
			href: '/spool/show/3'
		});
		expect(card?.rows[0].value).toMatch(/1.?234\.5 g/);
	});

	it('tags low-stock and on-order filaments', () => {
		const card = resultCard(
			'find_filaments',
			[{ id: 1, name: 'PLA', low_stock: true, on_order: true }],
			1,
			words,
			paths
		);
		expect(card?.rows[0].tags).toEqual(['low_stock', 'on_order']);
		expect(card?.more).toBe(0);
	});

	it('describes orders, locations, vendors and catalogue matches in words', () => {
		expect(
			resultCard(
				'find_orders',
				[{ id: 1, shop: 'Shop', status: 'open', outstanding_units: 2 }],
				1,
				words,
				paths
			)?.rows[0].detail
		).toBe('2 outstanding');
		expect(resultCard('find_orders', [{ id: 1, status: 'arrived' }], 1, words, paths)?.rows[0].detail).toBe(
			'Arrived'
		);
		expect(
			resultCard('find_locations', [{ id: 1, name: 'Shelf', spool_count: 4 }], 1, words, paths)?.rows[0]
				.detail
		).toBe('4 spools');
		expect(
			resultCard(
				'find_vendors',
				[{ id: 1, name: 'Acme', filament_count: 2, spool_count: 5 }],
				1,
				words,
				paths
			)?.rows[0].detail
		).toBe('2 filaments · 5 spools');
		expect(
			resultCard(
				'catalog_lookup',
				[{ external_id: 'x', vendor: 'Acme', name: 'PLA', match_percent: 91 }],
				1,
				words,
				paths
			)?.rows[0]
		).toMatchObject({ title: 'Acme · PLA', value: '91% match', href: null });
	});

	it('has no card for an unknown tool or an empty result', () => {
		expect(resultCard('mystery', [{ id: 1 }], 1, words, paths)).toBeNull();
		expect(resultCard('find_spools', [], 0, words, paths)).toBeNull();
		expect(resultCard('find_spools', undefined, undefined, words, paths)).toBeNull();
	});

	it('never links a row without a usable id', () => {
		const card = resultCard('find_spools', [{ id: 'x', filament: 'F' }], 1, words, paths);
		expect(card?.rows[0].href).toBeNull();
	});
});

describe('swatch colours', () => {
	it('accepts only 6 or 8 hex digits', () => {
		expect(swatchColour('ff0000')).toBe('#ff0000');
		expect(swatchColour('FF000080')).toBe('#FF000080');
		expect(swatchColour('red')).toBeNull();
		expect(swatchColour('ff0000;background:url(x)')).toBeNull();
		expect(swatchColour(null)).toBeNull();
	});
});

describe('usage bars', () => {
	it('scales each period to the busiest one', () => {
		const bars = usageBars([
			{ period: '2026-08', consumed_weight: 50 },
			{ period: '2026-09', consumed_weight: 200 },
			{ period: '2026-10', consumed_weight: 0 }
		]);
		expect(bars.map((b) => b.width)).toEqual([25, 100, 0]);
		expect(bars[1].value).toBe('200 g');
	});

	it('copes with nothing used at all, and with no periods', () => {
		expect(usageBars([{ period: 'a', consumed_weight: 0 }])[0].width).toBe(0);
		expect(usageBars([])).toEqual([]);
		expect(usageBars(undefined)).toEqual([]);
	});
});
