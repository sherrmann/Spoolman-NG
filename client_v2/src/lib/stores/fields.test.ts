// Spoolman NG fork addition (#482): a read that started before a save or delete must not put the
// older list back once the write has landed.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { FieldDef } from '$lib/api/fields';

const api = vi.hoisted(() => ({
	get: vi.fn(),
	set: vi.fn(),
	del: vi.fn()
}));
vi.mock('$lib/api/fields', () => ({
	getFields: api.get,
	setField: api.set,
	deleteField: api.del
}));

const field = (key: string, order = 0) => ({ key, name: key, order }) as unknown as FieldDef;

function deferred<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((res) => (resolve = res));
	return { promise, resolve };
}

async function freshStore() {
	vi.resetModules();
	return (await import('./fields.svelte')).fields;
}

describe('fields', () => {
	beforeEach(() => {
		api.get.mockReset();
		api.set.mockReset();
		api.del.mockReset();
	});

	it('keeps a field saved while an older read was still in flight', async () => {
		const read = deferred<FieldDef[]>();
		api.get.mockReturnValue(read.promise);
		api.set.mockResolvedValue([field('old'), field('new', 1)]);
		const store = await freshStore();

		const loading = store.load('spool');
		await store.save('spool', 'new', {} as never);
		read.resolve([field('old')]);
		await loading;

		expect(store.get('spool').map((f) => f.key)).toEqual(['old', 'new']);
		expect(store.isLoaded('spool')).toBe(true);
	});

	it('does not bring back a field deleted while an older read was in flight', async () => {
		const read = deferred<FieldDef[]>();
		api.get.mockReturnValue(read.promise);
		api.del.mockResolvedValue([]);
		const store = await freshStore();

		const loading = store.load('filament');
		await store.remove('filament', 'gone');
		read.resolve([field('gone')]);
		await loading;

		expect(store.get('filament')).toEqual([]);
	});

	it('applies a read that started after the last write', async () => {
		api.set.mockResolvedValue([field('a')]);
		api.get.mockResolvedValue([field('a'), field('b', 1)]);
		const store = await freshStore();

		await store.save('vendor', 'a', {} as never);
		await store.load('vendor');

		expect(store.get('vendor').map((f) => f.key)).toEqual(['a', 'b']);
	});

	it('starts one read per entity however often ensure is called', async () => {
		const read = deferred<FieldDef[]>();
		api.get.mockReturnValue(read.promise);
		const store = await freshStore();

		store.ensure('location');
		store.ensure('location');
		const loading = store.load('location');
		read.resolve([field('shelf')]);
		await loading;

		expect(api.get).toHaveBeenCalledTimes(1);
		expect(store.get('location').map((f) => f.key)).toEqual(['shelf']);
	});
});
