/**
 * Message access for this fork's own pages.
 *
 * Upstream's pages import `$lib/paraglide/messages`; this fork's import from here instead,
 * which is backed by the second inlang project (`project-ng.inlang`). Keeping the two apart is
 * what lets `git subtree pull` keep working -- see scripts/build_ng_messages.mjs.
 *
 * Both Paraglide runtimes read the same PARAGLIDE_LOCALE localStorage key, and the language
 * picker in settings reloads the page, so the two stay on the same locale without coordination.
 */
import * as messages from '$lib/paraglide-ng/messages';
import { getLocale } from '$lib/paraglide-ng/runtime';

export { messages as ng };

type MessageFn = (inputs?: Record<string, unknown>) => string;

const byId = messages as unknown as Record<string, MessageFn | undefined>;

/**
 * Resolve a CLDR-pluralized message, e.g. `home_kpi_materials` -> `..._one` / `..._other`.
 *
 * Which categories exist is a property of the language: English defines only `one` and `other`,
 * Polish also `few` and `many`. Paraglide compiles one message per suffix a locale actually
 * defines, and a message with no value in the current locale *and* no value in the base locale
 * returns its own id rather than throwing -- so an English page asking for `_few` would render
 * the literal string "home_kpi_materials_few". Falling back to `_other` on that sentinel keeps
 * a missing category rendering real text instead of an identifier.
 */
export function plural(base: string, count: number, inputs: Record<string, unknown> = {}): string {
	const category = new Intl.PluralRules(getLocale()).select(count);
	const args = { count, ...inputs };
	const exact = byId[`${base}_${category}`]?.(args);
	if (exact !== undefined && exact !== `${base}_${category}`) return exact;
	return byId[`${base}_other`]?.(args) ?? base;
}
