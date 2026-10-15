import {
	getFields,
	setField,
	deleteField,
	type EntityType,
	type FieldDef,
	type FieldParams
} from '$lib/api/fields';

// Reactive cache of extra-field definitions per entity type. Loaded on demand
// (inspectors) and by the settings manager; refetched after mutations.

// Spoolman NG fork addition: `location` and `printer` are this fork's entity types too.
const ENTITIES: EntityType[] = ['spool', 'filament', 'vendor', 'location', 'printer'];

function byOrder(list: FieldDef[]): FieldDef[] {
	return [...list].sort((a, b) => a.order - b.order || a.key.localeCompare(b.key));
}

class Fields {
	// Spoolman NG fork addition: the `location` and `printer` slots, forced by `Record<EntityType, …>`.
	private defs = $state<Record<EntityType, FieldDef[]>>({
		spool: [],
		filament: [],
		vendor: [],
		location: [],
		printer: []
	});
	// Reactive so views can wait for the definitions rather than render against an
	// empty list and then rearrange themselves once they arrive.
	private loaded = $state<EntityType[]>([]);
	// Spoolman NG fork addition (#482): the read in flight per entity, and a count of completed
	// writes. A read that started before a save or delete returns the list as it was then; applying
	// it afterwards would undo the write on screen. Neither needs to be reactive.
	private pending: Partial<Record<EntityType, Promise<void>>> = {};
	private writes: Partial<Record<EntityType, number>> = {};

	get(entity: EntityType): FieldDef[] {
		return this.defs[entity] ?? [];
	}

	/** Whether this entity's definitions are in hand — an empty list is a real answer. */
	isLoaded(entity: EntityType): boolean {
		return this.loaded.includes(entity);
	}

	/** Load once (idempotent). */
	ensure(entity: EntityType) {
		if (!this.loaded.includes(entity)) void this.load(entity);
	}

	/** Read an entity's definitions. A read already in flight is shared, not repeated. */
	load(entity: EntityType): Promise<void> {
		const inFlight = this.pending[entity];
		if (inFlight) return inFlight;
		const writesAtStart = this.writes[entity] ?? 0;
		const read = (async () => {
			try {
				const list = await getFields(entity);
				// A save or delete finished meanwhile: its list is newer than this one.
				if ((this.writes[entity] ?? 0) === writesAtStart) {
					this.defs = { ...this.defs, [entity]: byOrder(list) };
				}
				if (!this.loaded.includes(entity)) this.loaded = [...this.loaded, entity];
			} catch (e) {
				console.error(`Failed to load ${entity} fields`, e);
			} finally {
				delete this.pending[entity];
			}
		})();
		this.pending[entity] = read;
		return read;
	}

	loadAll() {
		for (const e of ENTITIES) void this.load(e);
	}

	async save(entity: EntityType, key: string, params: FieldParams) {
		const list = await setField(entity, key, params);
		this.applyWrite(entity, list);
	}

	async remove(entity: EntityType, key: string) {
		const list = await deleteField(entity, key);
		this.applyWrite(entity, list);
	}

	private applyWrite(entity: EntityType, list: FieldDef[]) {
		this.writes[entity] = (this.writes[entity] ?? 0) + 1;
		this.defs = { ...this.defs, [entity]: byOrder(list) };
	}
}

export const fields = new Fields();
