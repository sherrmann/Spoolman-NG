/**
 * Display text for the swatch styles (#415 step 3): a style's translated name, falling back
 * to the name the style registry gives it, so a style added there without a translation
 * still shows something readable.
 */
import { ng } from '$lib/ng/i18n';
import { SWATCH_STYLES } from '$lib/ng/swatch';

const byId = ng as unknown as Record<string, (() => string) | undefined>;

export function swatchStyleName(key: string): string {
	const style = SWATCH_STYLES.find((s) => s.key === key);
	return byId[`filament_swatch_styles_${key}`]?.() ?? style?.name ?? key;
}
