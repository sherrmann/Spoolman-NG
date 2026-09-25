/**
 * Multi-spool selection in the Library (#412, step 1 of docs/design/library-table-parity.md).
 *
 * The Library is upstream's: its rows are links that select ONE spool through the URL (`?sel=`),
 * and nothing in it knows about ticking several. This store is the fork's layer on top. The row
 * wrapper (`components/library/SpoolRow.svelte`) reads it to decide whether to draw a checkbox,
 * and registers each spool it renders, so "select all shown" knows what is on screen without the
 * list components having to tell it.
 *
 * Held in memory only. A selection restored from storage days later is an archive action waiting
 * to happen, so it lives exactly as long as the Library's toolbar: it survives paging, filtering
 * and opening the inspector, and is dropped by Clear, by turning the mode off, by a bulk action
 * that succeeded, and by leaving the Library (see LibraryModeControls).
 */
import { untrack } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';
import type { SpoolVM } from '$lib/utils/library';

export class LibrarySelection {
	/** Whether rows show a checkbox. Off is upstream's Library, untouched. */
	on = $state(false);

	/**
	 * The selected spools, each with the row it was selected from.
	 *
	 * Keeping the view model rather than just the id is what lets a spool on another page, or in
	 * a group that has since collapsed, still count towards "archive or unarchive?" and still have
	 * a name. A row that re-renders with newer data replaces it (see register).
	 */
	readonly selected = new SvelteMap<number, SpoolVM>();

	/** Rows currently rendered, counted, since nothing forbids one spool appearing twice. */
	// Deliberately not reactive: rows register while rendering, and only a click reads it.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	readonly #shown = new Map<number, { vm: SpoolVM; count: number }>();

	get count(): number {
		return this.selected.size;
	}

	has(id: number): boolean {
		return this.selected.has(id);
	}

	setMode(on: boolean): void {
		this.on = on;
		if (!on) this.clear();
	}

	toggle(vm: SpoolVM): void {
		const id = vm.spool.id;
		if (this.selected.has(id)) this.selected.delete(id);
		else this.selected.set(id, vm);
	}

	/** Add every spool whose row is on screen. Nothing already selected is dropped. */
	selectShown(): void {
		for (const [id, { vm }] of this.#shown) this.selected.set(id, vm);
	}

	/** Keep only these ids: after a bulk action, the ones that failed and can be retried. */
	retain(ids: Iterable<number>): void {
		// A local lookup table, never rendered.
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const keep = new Set(ids);
		for (const id of [...this.selected.keys()]) if (!keep.has(id)) this.selected.delete(id);
	}

	clear(): void {
		this.selected.clear();
	}

	/**
	 * A row came on screen, or re-rendered with newer data. Returns its unregister function.
	 *
	 * Called from each row's effect, so nothing here may be tracked. Reading `selected` would
	 * make every row re-register whenever any checkbox changes; worse, two rows showing the same
	 * spool with different view models (a group that has reloaded beside one that has not yet)
	 * would each overwrite the other's entry and wake the other's effect, without end.
	 */
	register(vm: SpoolVM): () => void {
		const id = vm.spool.id;
		const entry = this.#shown.get(id);
		this.#shown.set(id, { vm, count: (entry?.count ?? 0) + 1 });
		untrack(() => {
			if (this.selected.has(id) && this.selected.get(id) !== vm) this.selected.set(id, vm);
		});
		return () => {
			const current = this.#shown.get(id);
			if (!current) return;
			if (current.count <= 1) this.#shown.delete(id);
			else this.#shown.set(id, { vm: current.vm, count: current.count - 1 });
		};
	}

	/** How many spools are on screen: what "select all shown" would add. */
	get shownCount(): number {
		return this.#shown.size;
	}
}

/** What a selection holds, for deciding which archive action to offer. */
export function selectionSummary(vms: Iterable<SpoolVM>): { active: number[]; archived: number[] } {
	const active: number[] = [];
	const archived: number[] = [];
	for (const vm of vms) (vm.spool.archived ? archived : active).push(vm.spool.id);
	return { active, archived };
}

export const librarySelection = new LibrarySelection();
