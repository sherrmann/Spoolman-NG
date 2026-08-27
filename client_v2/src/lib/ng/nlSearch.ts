/**
 * Turning a natural-language search into this Library's own filter state.
 *
 * The server does the language part and hands back a small, generic shape: grounded filter
 * values, leftover free text, a colour, and a sort. Its job is to translate; this module's job
 * is to decide what of that translation this client can actually express -- and, just as
 * importantly, what it cannot.
 *
 * Two of the four fields have no home here, and pretending otherwise is the failure worth
 * avoiding. This client's spool list has no free-text parameter (see `listSpools` in
 * $lib/api/spoolSource -- sort, paging, archived and filters, nothing else) and no
 * colour-similarity filter at all. So a query like "matte black PETG on shelf B" yields two
 * filters this client applies and two parts it silently would not, unless something says so.
 * `unapplied` is that something: the caller reports it, and the user learns their search was
 * only half heard rather than wondering why the results look wrong.
 *
 * The field names differ on each side, and the mapping is not guessable -- the server speaks the
 * API's query parameters (`filament.vendor.name`) while the Library's chips are keyed by short
 * prop names (`vendor`) defined in $lib/api/spoolSource's FILTER_PARAM. This module is the one
 * place that knows both.
 */
import type { FilterChip } from '$lib/library/params';

/** One grounded filter as the server names it. */
export interface NlFilter {
	field: string;
	values: string[];
}

export interface NlSearchResult {
	filters: NlFilter[];
	search?: string | null;
	color_hex?: string | null;
	sort?: { field?: string; direction?: string } | null;
}

/** What a translated search asked for that this client has nowhere to put. */
export type UnappliedPart =
	/** Leftover free text; the Library filters by chips, not by a search string. */
	| 'search'
	/** A colour; there is no colour-similarity filter in this client. */
	| 'color'
	/** A sort field this Library does not offer. */
	| 'sort';

export interface NlSearchPlan {
	/** Chips to replace the current filters with. */
	filters: FilterChip[];
	/** The sort to switch to, when the server named one this Library has. */
	sortKey?: string;
	sortAsc?: boolean;
	/** Parts of the translation that could not be expressed here. */
	unapplied: UnappliedPart[];
}

/**
 * Server filter field -> Library chip prop.
 *
 * The inverse of FILTER_PARAM in $lib/api/spoolSource. Written out rather than derived from it
 * so an upstream change to that table shows up as a failing test here instead of as filters
 * that quietly stop matching.
 */
const FIELD_TO_PROP: Record<string, string> = {
	'filament.material': 'material',
	'filament.vendor.name': 'vendor',
	location: 'location',
	lot_nr: 'lot'
};

/**
 * Sort fields this Library can actually order by.
 *
 * The server restricts itself to a set (spoolman/nlsearch.py's _ALLOWED_SORT_FIELDS) that this
 * client happens to cover completely today. Checked anyway: a sort key the toolbar does not
 * know falls back to the default, so accepting one blindly would silently reorder the list by
 * something other than what was asked for.
 */
const SORTABLE = new Set([
	'remaining_weight',
	'used_weight',
	'first_used',
	'last_used',
	'registered',
	'location',
	'price'
]);

/**
 * Plan how to apply a translated search.
 *
 * Pure: it returns what to do rather than doing it, so the whole translation can be tested
 * without a Library, a URL or a browser.
 */
export function planNlSearch(result: NlSearchResult): NlSearchPlan {
	const filters: FilterChip[] = [];
	for (const f of result.filters ?? []) {
		const prop = FIELD_TO_PROP[f.field];
		// An unknown field is dropped rather than passed through as a chip: the Library would
		// render it as a filter it cannot label and the API would ignore it, which looks like
		// the search matched nothing.
		if (!prop) continue;
		for (const value of f.values ?? []) {
			if (value !== '') filters.push({ prop, value });
		}
	}

	const unapplied: UnappliedPart[] = [];
	if (result.search && result.search.trim()) unapplied.push('search');
	if (result.color_hex) unapplied.push('color');

	const plan: NlSearchPlan = { filters, unapplied };

	const field = result.sort?.field;
	if (field) {
		if (SORTABLE.has(field)) {
			plan.sortKey = field;
			plan.sortAsc = result.sort?.direction !== 'desc';
		} else {
			unapplied.push('sort');
		}
	}
	return plan;
}
