import { getJson, postJson, deleteJson } from './http';

// Extra-field DEFINITIONS (/api/v1/field/{entity_type}). These describe the
// custom fields available on each entity type; values live in each entity's
// `extra` map.

// Spoolman NG fork addition: `location` is a real entity type on this fork's backend
// (spoolman/extra_field_registry.py `EntityType`), so its field definitions come back from
// `GET /field/location` with `entity_type: "location"`; `printer` is registered there too, and
// the printers registry in this client (#413) carries each printer's `extra` values.
export type EntityType = 'spool' | 'filament' | 'vendor' | 'location' | 'printer';

export enum FieldType {
	text = 'text',
	integer = 'integer',
	integer_range = 'integer_range',
	float = 'float',
	float_range = 'float_range',
	datetime = 'datetime',
	boolean = 'boolean',
	choice = 'choice',
	// Spoolman NG fork addition: a short per-item value expanded into a URL through the
	// definition's `link_template` (#129).
	link = 'link'
}

/** Editable definition parameters (POST body). */
export interface FieldParams {
	name: string;
	order: number;
	unit?: string | null;
	field_type: FieldType;
	/** JSON-encoded default value string, or null. */
	default_value?: string | null;
	choices?: string[] | null;
	multi_choice?: boolean | null;
	// Spoolman NG fork addition. Base-URL template for a `link` field: `{}` is replaced by the
	// item's value, or the value is appended when there is no `{}`. Required for `link` and
	// rejected for every other type; max 512 characters (spoolman/extra_field_registry.py).
	link_template?: string | null;
	// Spoolman NG fork addition. Spool fields only: a new spool inherits this key's value from
	// its parent filament's same-key field at creation time, unless it supplies its own (#118).
	copy_from_filament?: boolean | null;
}

export interface FieldDef extends FieldParams {
	key: string;
	entity_type: EntityType;
}

export function getFields(entity: EntityType): Promise<FieldDef[]> {
	return getJson<FieldDef[]>(`/field/${entity}`);
}

/** Create or update a field; returns the full updated list. */
export function setField(entity: EntityType, key: string, params: FieldParams): Promise<FieldDef[]> {
	return postJson<FieldDef[]>(`/field/${entity}/${key}`, params);
}

/** Delete a field; returns the full updated list. */
export function deleteField(entity: EntityType, key: string): Promise<FieldDef[]> {
	return deleteJson<FieldDef[]>(`/field/${entity}/${key}`);
}

export const NUMERIC_FIELD_TYPES = new Set<FieldType>([
	FieldType.integer,
	FieldType.integer_range,
	FieldType.float,
	FieldType.float_range
]);

export const RANGE_FIELD_TYPES = new Set<FieldType>([FieldType.integer_range, FieldType.float_range]);

export const FIELD_TYPE_LABELS: Record<FieldType, string> = {
	[FieldType.text]: 'Text',
	[FieldType.integer]: 'Integer',
	[FieldType.integer_range]: 'Integer range',
	[FieldType.float]: 'Float',
	[FieldType.float_range]: 'Float range',
	[FieldType.datetime]: 'Date & time',
	[FieldType.boolean]: 'Boolean',
	[FieldType.choice]: 'Choice',
	// Spoolman NG fork addition.
	[FieldType.link]: 'Link'
};
