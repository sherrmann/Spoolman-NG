import { describe, expect, it } from 'vitest';
import { buildEditedLines, buildOrderPatchBody } from './orderEditBody';
import type { OrderEditLineInput } from './orderEditBody';
import type { OrderLine } from './types';

describe('buildEditedLines', () => {
	it("passes arrived lines through unchanged, including arrivedAt, so the full-replace PATCH doesn't un-arrive them", () => {
		const original: OrderLine[] = [
			{ id: 1, filamentId: '10', quantity: 3, pricePerUnit: 19.9, arrivedAt: '2026-07-01T00:00:00Z' },
			{ id: 2, filamentId: '11', quantity: 2, pricePerUnit: undefined, arrivedAt: undefined }
		];
		const result = buildEditedLines(original, {});
		expect(result).toEqual([
			{ filamentId: '10', quantity: 3, pricePerUnit: 19.9, arrivedAt: '2026-07-01T00:00:00Z' },
			{ filamentId: '11', quantity: 2, pricePerUnit: undefined }
		]);
	});

	it('applies edits (quantity/pricePerUnit) only to the matching un-arrived line', () => {
		const original: OrderLine[] = [
			{ id: 1, filamentId: '10', quantity: 3, pricePerUnit: 19.9, arrivedAt: '2026-07-01T00:00:00Z' },
			{ id: 2, filamentId: '11', quantity: 2, pricePerUnit: 5, arrivedAt: undefined }
		];
		const result = buildEditedLines(original, { 2: { quantity: 4, pricePerUnit: 7.5 } });
		expect(result).toEqual([
			{ filamentId: '10', quantity: 3, pricePerUnit: 19.9, arrivedAt: '2026-07-01T00:00:00Z' },
			{ filamentId: '11', quantity: 4, pricePerUnit: 7.5 }
		]);
	});

	it("ignores an edit keyed to an arrived line's id (arrived lines are read-only)", () => {
		const original: OrderLine[] = [
			{ id: 1, filamentId: '10', quantity: 3, pricePerUnit: 19.9, arrivedAt: '2026-07-01T00:00:00Z' }
		];
		const result = buildEditedLines(original, { 1: { quantity: 99, pricePerUnit: 1 } });
		expect(result).toEqual([
			{ filamentId: '10', quantity: 3, pricePerUnit: 19.9, arrivedAt: '2026-07-01T00:00:00Z' }
		]);
	});

	it('falls back to the original quantity/pricePerUnit when an edit omits one of them', () => {
		const original: OrderLine[] = [
			{ id: 1, filamentId: '10', quantity: 3, pricePerUnit: 19.9, arrivedAt: undefined }
		];
		const result = buildEditedLines(original, { 1: { quantity: 5, pricePerUnit: undefined } });
		// An edit row always carries both fields in practice (seeded from the line), but the builder
		// must not silently invent a price the line never had if a caller only supplies quantity.
		expect(result).toEqual([{ filamentId: '10', quantity: 5, pricePerUnit: undefined }]);
	});

	it('returns an empty array for an order with no lines', () => {
		expect(buildEditedLines([], {})).toEqual([]);
	});
});

describe('buildOrderPatchBody', () => {
	const lines: OrderEditLineInput[] = [{ filamentId: '10', quantity: 2, pricePerUnit: 19.9 }];

	it('builds a full PATCH body with shop, order number, url and comment set', () => {
		expect(
			buildOrderPatchBody(
				{
					shopId: 5,
					orderedAt: '2026-07-01T00:00:00Z',
					orderNumber: '4711',
					url: 'https://shop/4711',
					comment: 'Backordered'
				},
				lines
			)
		).toEqual({
			shop_id: 5,
			ordered_at: '2026-07-01T00:00:00Z',
			order_number: '4711',
			url: 'https://shop/4711',
			comment: 'Backordered',
			lines: [{ filament_id: 10, quantity: 2, price_per_unit: 19.9 }]
		});
	});

	it('nulls out order_number/url/comment when they were cleared (blank/whitespace), and shop_id when no shop is chosen', () => {
		expect(
			buildOrderPatchBody(
				{ shopId: null, orderedAt: '2026-07-19T00:00:00Z', orderNumber: '  ', url: '', comment: '   ' },
				lines
			)
		).toEqual({
			shop_id: null,
			ordered_at: '2026-07-19T00:00:00Z',
			order_number: null,
			url: null,
			comment: null,
			lines: [{ filament_id: 10, quantity: 2, price_per_unit: 19.9 }]
		});
	});

	it('trims order_number/url/comment before sending them', () => {
		expect(
			buildOrderPatchBody(
				{
					shopId: 1,
					orderedAt: '2026-07-19T00:00:00Z',
					orderNumber: ' 4711 ',
					url: ' https://x ',
					comment: ' hi '
				},
				lines
			)
		).toEqual({
			shop_id: 1,
			ordered_at: '2026-07-19T00:00:00Z',
			order_number: '4711',
			url: 'https://x',
			comment: 'hi',
			lines: [{ filament_id: 10, quantity: 2, price_per_unit: 19.9 }]
		});
	});

	// The React source's equivalent test checked buildOrderPatchBody's lines output equals its
	// (already wire-shaped) input by reference-free copy. Here the builder also performs the
	// domain->wire conversion (filamentId string -> filament_id number, per orderBody.ts's
	// convention), so the output is never reference-equal *or* structurally equal to the domain
	// input -- what matters is that the input is left untouched and each output line is a fresh
	// object.
	it('does not mutate its lines input and builds fresh wire line objects', () => {
		const body = buildOrderPatchBody(
			{ shopId: 1, orderedAt: '2026-07-19T00:00:00Z', orderNumber: '', url: '', comment: '' },
			lines
		);
		expect(lines).toEqual([{ filamentId: '10', quantity: 2, pricePerUnit: 19.9 }]);
		expect(body.lines).toEqual([{ filament_id: 10, quantity: 2, price_per_unit: 19.9 }]);
		expect(body.lines[0]).not.toBe(lines[0]);
	});
});
