/**
 * Display text for the catalogue fields (#415), shared by the inspector rows and the library's
 * columns. Unknown is an empty string: a column cell stays blank, as for any unset field.
 */
import { ng } from '$lib/ng/i18n';
import type { FilamentNg } from './filamentCatalogue';

const byId = ng as unknown as Record<string, (() => string) | undefined>;

/** A translated option label, e.g. `('finish', 'matte')` → "Matte"; the raw value if untranslated. */
export function optionText(group: 'spool_type' | 'finish' | 'pattern', value: string): string {
	return byId[`filament_${group}_options_${value}`]?.() ?? value;
}

export function yesNoText(value: boolean | null): string {
	return value === null ? '' : value ? ng.yes() : ng.no();
}

export function catalogueText(key: keyof FilamentNg, f: FilamentNg | undefined): string {
	if (!f) return '';
	switch (key) {
		case 'spoolType':
			return f.spoolType ? optionText('spool_type', f.spoolType) : '';
		case 'finish':
			return f.finish ? optionText('finish', f.finish) : '';
		case 'pattern':
			return f.pattern ? optionText('pattern', f.pattern) : '';
		case 'translucent':
		case 'glow':
			return yesNoText(f[key]);
	}
}
