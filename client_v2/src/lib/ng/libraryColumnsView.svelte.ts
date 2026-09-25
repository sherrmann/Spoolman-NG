/**
 * The column layout everything in the flat list draws from (#412 step 5): the catalogue for
 * today's extra fields, the visible columns and the one grid template the header and every
 * row share, so they cannot drift out of line.
 */
import { fields } from '$lib/stores/fields.svelte';
import { columnCatalogue, type ColumnDef } from './libraryColumnCatalogue';
import { gridTemplate, minGridWidth } from './libraryColumns';
import { libraryColumns } from './libraryColumns.svelte';

class ColumnsView {
	catalogue = $derived<ColumnDef[]>(columnCatalogue(fields.get('spool')));
	ids = $derived(this.catalogue.map((c) => c.id));
	byId = $derived(new Map(this.catalogue.map((c) => [c.id, c])));
	/** Whether the user has configured columns at all; until then rows are upstream's. */
	custom = $derived(libraryColumns.config !== null);
	visible = $derived(libraryColumns.visible(this.ids));
	#defaults = $derived(Object.fromEntries(this.catalogue.map((c) => [c.id, c.width])));
	template = $derived(gridTemplate(this.visible, libraryColumns.config?.widths ?? {}, this.#defaults));
	/**
	 * The narrowest the header and every row may be. The same number for all of them, so when the
	 * columns are wider than the pane they all overflow alike and the list scrolls sideways with
	 * everything still in line; sizing each row to its own content would not.
	 */
	minWidth = $derived(minGridWidth(this.visible, libraryColumns.config?.widths ?? {}, this.#defaults));
}

export const columnsView = new ColumnsView();
