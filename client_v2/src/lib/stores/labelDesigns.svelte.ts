import { getDesignsSetting, saveDesigns } from '$lib/api/labelDesigns';
import { importV1Presets } from '$lib/labels/migrateV1';
import { newDesign, type LabelDesign } from '$lib/labels/types';

// Reactive, server-backed collection of label designs. Mirrors the pattern in
// settings.svelte.ts: a singleton runes class loaded once, mutations persisted
// to the `label_designs` setting.

function uid(): string {
	return typeof crypto !== 'undefined' && crypto.randomUUID
		? crypto.randomUUID()
		: `d-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

class LabelDesigns {
	designs = $state<LabelDesign[]>([]);
	/** True only once the designs have been read from the server; a failed read leaves it false. */
	loaded = $state(false);
	// Spoolman NG fork addition (#481): the read in flight, so concurrent callers share it and a
	// mutation can wait for it. Every write sends the whole list, so writing before the read has
	// landed would replace the stored designs with whatever happens to be in memory.
	private pending: Promise<void> | null = null;

	load(): Promise<void> {
		// The pending read first: on first run it also covers saving the v1 import, and a change
		// that skipped it because `loaded` is already true could be overwritten by that save.
		if (this.pending) return this.pending;
		if (this.loaded) return Promise.resolve();
		this.pending = this.fetch().finally(() => (this.pending = null));
		return this.pending;
	}

	private async fetch(): Promise<void> {
		try {
			const { designs, isSet } = await getDesignsSetting();
			// First run (setting never written): pull the v1 client's print presets
			// across so upgrading users keep their labels. Only persist when there was
			// something to import, so a genuinely new user still starts empty.
			if (!isSet) {
				const imported = await importV1Presets();
				if (imported.length > 0) {
					this.designs = imported;
					// The read itself succeeded, so the list in memory is the right one to write later
					// even if saving the import fails now. Leaving the store unloaded would re-run the
					// import on the next change and hand out fresh ids, duplicating every design.
					this.loaded = true;
					try {
						await this.persist();
					} catch (e) {
						console.error('Failed to save the imported label designs', e);
					}
					return;
				}
			}
			this.designs = designs;
			this.loaded = true;
		} catch (e) {
			console.error('Failed to load label designs', e);
		}
	}

	/** Wait for (or retry) the read; refuse to write over designs that could not be read. */
	private async ready(): Promise<void> {
		await this.load();
		if (!this.loaded) throw new Error('Label designs could not be loaded, so they will not be overwritten.');
	}

	private async persist(): Promise<void> {
		await saveDesigns($state.snapshot(this.designs) as LabelDesign[]);
	}

	/** Create and persist a fresh design; returns it. */
	async create(): Promise<LabelDesign> {
		await this.ready();
		const design = newDesign(uid());
		this.designs = [...this.designs, design];
		await this.persist();
		return design;
	}

	/** Insert or replace a design by id, then persist. */
	async save(design: LabelDesign): Promise<void> {
		await this.ready();
		const idx = this.designs.findIndex((d) => d.id === design.id);
		if (idx === -1) this.designs = [...this.designs, design];
		else this.designs = this.designs.map((d) => (d.id === design.id ? design : d));
		await this.persist();
	}

	/** Duplicate a design under a new id/name; returns the copy. */
	async duplicate(id: string): Promise<LabelDesign | undefined> {
		await this.ready();
		const src = this.designs.find((d) => d.id === id);
		if (!src) return undefined;
		const copy: LabelDesign = {
			...structuredClone($state.snapshot(src) as LabelDesign),
			id: uid(),
			name: `${src.name} copy`
		};
		this.designs = [...this.designs, copy];
		await this.persist();
		return copy;
	}

	async remove(id: string): Promise<void> {
		await this.ready();
		this.designs = this.designs.filter((d) => d.id !== id);
		await this.persist();
	}
}

export const labelDesigns = new LabelDesigns();
