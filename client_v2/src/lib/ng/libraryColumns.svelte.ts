import {
	COLUMNS_KEY,
	clampWidth,
	moveColumn,
	normaliseConfig,
	parseStoredColumns,
	visibleColumns,
	FLEX_COLUMN,
	type ColumnsConfig
} from './libraryColumns';

function read(): ColumnsConfig | null {
	try {
		return parseStoredColumns(typeof localStorage === 'undefined' ? null : localStorage.getItem(COLUMNS_KEY));
	} catch {
		return null;
	}
}

/**
 * The Library's column configuration, remembered per browser (#412 step 5). `config` is null
 * until the user changes something, and null means upstream's own row; see libraryColumns.ts.
 */
class LibraryColumnsState {
	config = $state<ColumnsConfig | null>(read());

	#base(catalogue: readonly string[]): ColumnsConfig {
		return normaliseConfig(this.config, catalogue);
	}

	#save(next: ColumnsConfig): void {
		this.config = next;
		this.persist();
	}

	/** The columns to render, in order. */
	visible(catalogue: readonly string[]): string[] {
		return visibleColumns(this.#base(catalogue), catalogue);
	}

	toggle(id: string, catalogue: readonly string[]): void {
		const c = this.#base(catalogue);
		const hidden = c.hidden.includes(id) ? c.hidden.filter((h) => h !== id) : [...c.hidden, id];
		// The name is what identifies a row; a list without it is a list of numbers.
		if (id === FLEX_COLUMN && hidden.includes(id)) return;
		this.#save({ ...c, hidden });
	}

	move(id: string, delta: -1 | 1, catalogue: readonly string[]): void {
		const c = this.#base(catalogue);
		this.#save({ ...c, order: moveColumn(c.order, id, delta) });
	}

	/** Set while dragging; `persist` once the drag ends, not on every pointer move. */
	setWidth(id: string, width: number, catalogue: readonly string[]): void {
		const c = this.#base(catalogue);
		this.config = { ...c, widths: { ...c.widths, [id]: clampWidth(width) } };
	}

	persist(): void {
		try {
			if (this.config === null) localStorage.removeItem(COLUMNS_KEY);
			else localStorage.setItem(COLUMNS_KEY, JSON.stringify(this.config));
		} catch {
			/* remembering the layout is a convenience */
		}
	}

	/** Back to upstream's row, by forgetting the configuration. */
	reset(): void {
		this.config = null;
		this.persist();
	}
}

export const libraryColumns = new LibraryColumnsState();
