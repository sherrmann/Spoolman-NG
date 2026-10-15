// Spoolman NG fork addition (#481): mutations must not write the whole design list before it
// has been read, or the stored designs are replaced by whatever happens to be in memory.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { LabelDesign } from '$lib/labels/types';

const api = vi.hoisted(() => ({
	get: vi.fn(),
	save: vi.fn()
}));
vi.mock('$lib/api/labelDesigns', () => ({
	getDesignsSetting: api.get,
	saveDesigns: api.save
}));
const v1 = vi.hoisted(() => ({ presets: vi.fn() }));
vi.mock('$lib/labels/migrateV1', () => ({ importV1Presets: v1.presets }));

const stored = [{ id: 'kept', name: 'Kept' } as LabelDesign];

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

async function freshStore() {
	vi.resetModules();
	return (await import('./labelDesigns.svelte')).labelDesigns;
}

describe('labelDesigns', () => {
	beforeEach(() => {
		api.get.mockReset();
		api.save.mockReset().mockResolvedValue(undefined);
		v1.presets.mockReset().mockResolvedValue([]);
	});

	it('waits for a slow first read before creating, and keeps the stored designs', async () => {
		const read = deferred<{ designs: LabelDesign[]; isSet: boolean }>();
		api.get.mockReturnValue(read.promise);
		const store = await freshStore();

		const loading = store.load();
		const creating = store.create();
		expect(api.save).not.toHaveBeenCalled();

		read.resolve({ designs: stored, isSet: true });
		await loading;
		const created = await creating;

		expect(api.save).toHaveBeenCalledTimes(1);
		const written = api.save.mock.calls[0][0] as LabelDesign[];
		expect(written.map((d) => d.id)).toEqual(['kept', created.id]);
		expect(store.designs.map((d) => d.id)).toEqual(['kept', created.id]);
	});

	it('refuses to write over designs that could not be read', async () => {
		api.get.mockRejectedValue(new Error('offline'));
		const store = await freshStore();
		vi.spyOn(console, 'error').mockImplementation(() => {});

		await store.load();
		expect(store.loaded).toBe(false);
		await expect(store.create()).rejects.toThrow(/could not be loaded/);
		await expect(store.remove('kept')).rejects.toThrow(/could not be loaded/);
		expect(api.save).not.toHaveBeenCalled();
	});

	it('retries the read on the next mutation once the server answers', async () => {
		api.get.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ designs: stored, isSet: true });
		const store = await freshStore();
		vi.spyOn(console, 'error').mockImplementation(() => {});

		await store.load();
		const created = await store.create();

		const written = api.save.mock.calls[0][0] as LabelDesign[];
		expect(written.map((d) => d.id)).toEqual(['kept', created.id]);
	});

	it('shares one read between concurrent callers', async () => {
		api.get.mockResolvedValue({ designs: stored, isSet: true });
		const store = await freshStore();

		await Promise.all([store.load(), store.load(), store.save({ ...stored[0], name: 'Renamed' })]);

		expect(api.get).toHaveBeenCalledTimes(1);
		expect(store.designs).toEqual([{ id: 'kept', name: 'Renamed' }]);
	});

	it('keeps the imported v1 presets, ids and all, when saving the import fails', async () => {
		// First run: nothing stored yet, so the v1 presets are imported. Their ids are fresh on each
		// import, so a second import would duplicate every design the page is already showing.
		api.get.mockResolvedValue({ designs: [], isSet: false });
		let n = 0;
		v1.presets.mockImplementation(async () => [{ id: `imp${++n}`, name: 'Imported' } as LabelDesign]);
		api.save.mockRejectedValueOnce(new Error('offline'));
		const store = await freshStore();
		vi.spyOn(console, 'error').mockImplementation(() => {});

		await store.load();
		expect(store.loaded).toBe(true);
		await store.save({ id: 'imp1', name: 'Edited' } as LabelDesign);

		expect(v1.presets).toHaveBeenCalledTimes(1);
		expect(api.save.mock.calls.at(-1)?.[0]).toEqual([{ id: 'imp1', name: 'Edited' }]);
	});

	it('makes a change made while the v1 import is being saved wait for that save', async () => {
		api.get.mockResolvedValue({ designs: [], isSet: false });
		v1.presets.mockResolvedValue([{ id: 'imp1', name: 'Imported' } as LabelDesign]);
		const importSave = deferred<void>();
		api.save.mockReturnValueOnce(importSave.promise);
		const store = await freshStore();

		const loading = store.load();
		await vi.waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
		const creating = store.create();
		// Let every microtask run: without the wait, create() would already have written by now.
		await new Promise((r) => setTimeout(r, 0));
		expect(api.save).toHaveBeenCalledTimes(1);

		importSave.resolve();
		await loading;
		const created = await creating;

		expect(api.save).toHaveBeenCalledTimes(2);
		const written = api.save.mock.calls[1][0] as LabelDesign[];
		expect(written.map((d) => d.id)).toEqual(['imp1', created.id]);
	});
});
