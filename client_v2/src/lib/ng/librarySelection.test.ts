import { describe, expect, it } from 'vitest';
import type { SpoolVM } from '$lib/utils/library';
import { LibrarySelection, selectionSummary } from './librarySelection.svelte';

// Only the fields the store reads; a SpoolVM is otherwise a whole rendered row.
function vm(id: number, archived = false, label = `#${id}`): SpoolVM {
	return { spool: { id, archived }, idLabel: label } as unknown as SpoolVM;
}

describe('LibrarySelection', () => {
	it('toggles a spool in and out', () => {
		const s = new LibrarySelection();
		s.toggle(vm(1));
		s.toggle(vm(2));
		s.toggle(vm(1));
		expect([...s.selected.keys()]).toEqual([2]);
	});

	it('selects every row on screen, adding to what is already selected', () => {
		const s = new LibrarySelection();
		s.toggle(vm(9)); // on another page, no longer shown
		s.register(vm(1));
		s.register(vm(2));
		s.selectShown();
		expect([...s.selected.keys()].sort()).toEqual([1, 2, 9]);
	});

	it('forgets a row once every copy of it has left the screen', () => {
		const s = new LibrarySelection();
		const first = s.register(vm(1));
		const second = s.register(vm(1));
		first();
		expect(s.shownCount).toBe(1);
		second();
		s.selectShown();
		expect(s.count).toBe(0);
	});

	it('keeps an off-screen spool’s row, and takes a newer one when it re-renders', () => {
		const s = new LibrarySelection();
		const unregister = s.register(vm(1, false));
		s.toggle(vm(1, false));
		unregister();
		expect(s.selected.get(1)?.spool.archived).toBe(false);

		s.register(vm(1, true));
		expect(s.selected.get(1)?.spool.archived).toBe(true);
	});

	it('does not select a spool just because its row re-rendered', () => {
		const s = new LibrarySelection();
		s.register(vm(1));
		expect(s.has(1)).toBe(false);
	});

	it('keeps only the given ids, so failed spools can be retried', () => {
		const s = new LibrarySelection();
		for (const id of [1, 2, 3]) s.toggle(vm(id));
		s.retain([2, 7]);
		expect([...s.selected.keys()]).toEqual([2]);
	});

	it('drops the selection when the mode is turned off', () => {
		const s = new LibrarySelection();
		s.setMode(true);
		s.toggle(vm(1));
		s.setMode(false);
		expect(s.count).toBe(0);
		expect(s.on).toBe(false);
	});
});

describe('selectionSummary', () => {
	it('splits the selection into active and archived spools', () => {
		expect(selectionSummary([vm(1), vm(2, true), vm(3)])).toEqual({ active: [1, 3], archived: [2] });
	});
});
