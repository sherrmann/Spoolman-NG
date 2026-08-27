import { describe, expect, it } from 'vitest';
import { buildBulkOrderBody, buildMarkOrderedBody, buildNewOrderBody } from './orderBody';

describe('buildMarkOrderedBody', () => {
	it('builds a one-line order with shop, price, number, url and the backdated ordered_at', () => {
		expect(
			buildMarkOrderedBody({
				filamentId: '7',
				quantity: 2,
				orderedAt: '2026-08-20T09:00:00Z',
				shopId: 3,
				pricePerUnit: 24.99,
				orderNumber: 'SO-4711',
				url: 'https://shop.example/orders/4711'
			})
		).toEqual({
			ordered_at: '2026-08-20T09:00:00Z',
			shop_id: 3,
			order_number: 'SO-4711',
			url: 'https://shop.example/orders/4711',
			lines: [{ filament_id: 7, quantity: 2, price_per_unit: 24.99 }]
		});
	});

	it('omits shop, price, number and url when not given', () => {
		expect(buildMarkOrderedBody({ filamentId: '7', quantity: 1, orderedAt: '2026-08-20T09:00:00Z' })).toEqual(
			{ ordered_at: '2026-08-20T09:00:00Z', lines: [{ filament_id: 7, quantity: 1 }] }
		);
	});

	// An empty string is what a cleared input yields. Sending it would store a blank order number
	// that reads as a real one in the orders list, so falsy is treated as "not given".
	it('treats a blank order number or url as not given', () => {
		const body = buildMarkOrderedBody({
			filamentId: '7',
			quantity: 1,
			orderedAt: '2026-08-20T09:00:00Z',
			orderNumber: '',
			url: ''
		});
		expect(body).not.toHaveProperty('order_number');
		expect(body).not.toHaveProperty('url');
	});
});

describe('buildBulkOrderBody', () => {
	it('maps selected filaments to one order with one line each', () => {
		expect(
			buildBulkOrderBody(
				[
					{ filamentId: '1', quantity: 2, pricePerUnit: 19.9 },
					{ filamentId: '2', quantity: 1 }
				],
				'2026-08-21T10:00:00Z',
				5
			)
		).toEqual({
			ordered_at: '2026-08-21T10:00:00Z',
			shop_id: 5,
			lines: [
				{ filament_id: 1, quantity: 2, price_per_unit: 19.9 },
				{ filament_id: 2, quantity: 1 }
			]
		});
	});

	it('omits shop_id when no shop was chosen', () => {
		const body = buildBulkOrderBody([{ filamentId: '1', quantity: 1 }], '2026-08-21T10:00:00Z');
		expect(body).not.toHaveProperty('shop_id');
	});
});

describe('buildNewOrderBody', () => {
	it('builds a full order with header and one line per picked filament', () => {
		expect(
			buildNewOrderBody({
				orderedAt: '2026-08-22T08:00:00Z',
				lines: [
					{ filamentId: '4', quantity: 3, pricePerUnit: 12.5 },
					{ filamentId: '9', quantity: 1 }
				],
				shopId: 2,
				orderNumber: 'PO-9',
				url: 'https://shop.example/po/9',
				comment: 'restock'
			})
		).toEqual({
			ordered_at: '2026-08-22T08:00:00Z',
			shop_id: 2,
			order_number: 'PO-9',
			url: 'https://shop.example/po/9',
			comment: 'restock',
			lines: [
				{ filament_id: 4, quantity: 3, price_per_unit: 12.5 },
				{ filament_id: 9, quantity: 1 }
			]
		});
	});

	it('omits the optional header fields when they are not given', () => {
		const body = buildNewOrderBody({
			orderedAt: '2026-08-22T08:00:00Z',
			lines: [{ filamentId: '4', quantity: 1 }]
		});
		expect(body).toEqual({
			ordered_at: '2026-08-22T08:00:00Z',
			lines: [{ filament_id: 4, quantity: 1 }]
		});
	});

	// The builder must not alias the caller's draft: the modal keeps editing its rows while the
	// request is in flight, and a shared reference would let a later keystroke change what was
	// already sent.
	it('does not alias the caller’s draft lines', () => {
		const draft = [{ filamentId: '4', quantity: 1 }];
		const body = buildNewOrderBody({ orderedAt: '2026-08-22T08:00:00Z', lines: draft });
		draft[0].quantity = 99;
		expect(body.lines[0].quantity).toBe(1);
	});
});

// New behaviour, not in the React original, which took ids as numbers already. This client holds
// them as strings so oversized CockroachDB ids survive; converting one that cannot be an exact
// integer would silently bind the line to a different filament, so it must fail loudly.
describe('filament id precision guard', () => {
	it('rejects an id too large to be an exact integer', () => {
		expect(() =>
			buildBulkOrderBody([{ filamentId: '9007199254740993', quantity: 1 }], '2026-08-21T10:00:00Z')
		).toThrow(/precision/);
	});

	it('rejects an id that is not an integer at all', () => {
		expect(() => buildBulkOrderBody([{ filamentId: 'abc', quantity: 1 }], '2026-08-21T10:00:00Z')).toThrow(
			/precision/
		);
	});

	it('accepts an ordinary id', () => {
		expect(
			buildBulkOrderBody([{ filamentId: '42', quantity: 1 }], '2026-08-21T10:00:00Z').lines[0].filament_id
		).toBe(42);
	});
});
