import { describe, expect, it } from 'vitest';
import { bulkApply } from './bulkPatch';

const tick = () => new Promise((r) => setTimeout(r, 0));

describe('bulkApply', () => {
	it('reports which ids succeeded and which failed', async () => {
		const result = await bulkApply([1, 2, 3, 4], async (id) => {
			if (id % 2 === 0) throw new Error(`no ${id}`);
		});
		expect(result.ok.sort()).toEqual([1, 3]);
		expect(result.failed.map((f) => f.id).sort()).toEqual([2, 4]);
		expect((result.failed[0].error as Error).message).toMatch(/^no /);
	});

	it('never has more than `concurrency` writes in flight', async () => {
		let inFlight = 0;
		let peak = 0;
		const ids = Array.from({ length: 20 }, (_, i) => i);
		const result = await bulkApply(
			ids,
			async () => {
				inFlight++;
				peak = Math.max(peak, inFlight);
				await tick();
				inFlight--;
			},
			{ concurrency: 3 }
		);
		expect(peak).toBe(3);
		expect(result.ok.sort((a, b) => a - b)).toEqual(ids);
	});

	it('writes each id exactly once', async () => {
		const seen: number[] = [];
		await bulkApply([5, 6, 7], async (id) => void seen.push(id), { concurrency: 8 });
		expect(seen.sort()).toEqual([5, 6, 7]);
	});

	it('makes no call for an empty selection', async () => {
		let calls = 0;
		expect(await bulkApply([], async () => void calls++)).toEqual({ ok: [], failed: [] });
		expect(calls).toBe(0);
	});
});
