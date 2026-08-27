import { describe, expect, it } from 'vitest';
import { formatOrderedPill, summarizeLines } from './ordersState';
import type { Order, OrderLine } from './types';

function order(over: Partial<Order> = {}): Order {
	return {
		id: 1,
		orderedAt: '2026-07-10T00:00:00Z',
		lines: [],
		state: 'open',
		...over
	};
}

describe('summarizeLines', () => {
	it('rolls quantities into total/arrived/outstanding + filament count', () => {
		const lines: OrderLine[] = [
			{ id: 1, filamentId: '1', quantity: 4, arrivedAt: '2026-07-11T00:00:00Z' },
			{ id: 2, filamentId: '2', quantity: 3 }
		];
		expect(summarizeLines(order({ lines }))).toEqual({ total: 7, arrived: 4, outstanding: 3, filaments: 2 });
	});

	it('reports zero for a note-only order', () => {
		expect(summarizeLines(order({ lines: [] }))).toEqual({
			total: 0,
			arrived: 0,
			outstanding: 0,
			filaments: 0
		});
	});

	it('counts distinct filament_ids, not lines — a split line must not double-count', () => {
		const lines: OrderLine[] = [
			{ id: 1, filamentId: '5', quantity: 2 },
			{ id: 2, filamentId: '5', quantity: 3, arrivedAt: '2026-07-11T00:00:00Z' }
		];
		expect(summarizeLines(order({ lines })).filaments).toBe(1);
	});

	it('open order with outstanding lines reports a positive outstanding count for the state pill', () => {
		const lines: OrderLine[] = [
			{ id: 1, filamentId: '1', quantity: 2 },
			{ id: 2, filamentId: '2', quantity: 1, arrivedAt: '2026-07-11T00:00:00Z' }
		];
		expect(summarizeLines(order({ state: 'open', lines })).outstanding).toBe(2);
	});

	it('fully arrived order reports zero outstanding for the state pill', () => {
		const lines: OrderLine[] = [{ id: 1, filamentId: '1', quantity: 3, arrivedAt: '2026-07-11T00:00:00Z' }];
		expect(summarizeLines(order({ state: 'arrived', lines })).outstanding).toBe(0);
	});
});

describe('formatOrderedPill', () => {
	const now = new Date('2026-07-19T00:00:00Z');

	it('shows age and shop', () => {
		expect(formatOrderedPill({ orderId: 1, orderedAt: '2026-07-16T00:00:00Z' }, '3DJake', now)).toBe(
			'Ordered · 3d · 3DJake'
		);
	});

	it('omits the shop when unknown', () => {
		expect(formatOrderedPill({ orderId: 1, orderedAt: '2026-07-18T00:00:00Z' }, undefined, now)).toBe(
			'Ordered · 1d'
		);
	});

	it("uses 'today' for a same-day order", () => {
		expect(formatOrderedPill({ orderId: 1, orderedAt: '2026-07-19T00:00:00Z' }, 'Prusa', now)).toBe(
			'Ordered · today · Prusa'
		);
	});
});
