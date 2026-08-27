#!/usr/bin/env node
/**
 * Generate the Svelte client's fork-only messages from the React client's translations.
 *
 * The Svelte client (`client_v2/`) is vendored from upstream as a git subtree, and upstream
 * points Weblate at `client_v2/locales/`. Adding this fork's strings there would collide on
 * every `git subtree pull`, so fork strings live in their own inlang project instead --
 * `client_v2/project-ng.inlang/`, compiled to a separate Paraglide module.
 *
 * The source of truth is the React client's existing i18next catalogue, which already carries
 * these exact strings in 32 languages. It is not read directly by inlang: `@inlang/plugin-i18next`
 * treats an underscore in a key as i18next's *context* separator, so `home.total_weight` and
 * `home.total_value` collapse into one `home.total` message taking `{ context }`, and a call
 * that guesses the split wrong renders the raw key instead of failing the build. Measured
 * against the keys these pages need, 29 of 51 were re-split that way. So this script
 * transcribes the subset we use into `@inlang/plugin-message-format`, whose ids are opaque.
 *
 * Output lands in client_v2/locales-ng/ rather than inside the project directory: inlang
 * manages a .gitignore inside every *.inlang directory that ignores all but settings.json,
 * and upstream's own project keeps its messages in a sibling directory for the same reason.
 *
 * Run after changing KEYS, or after translations land in client/public/locales:
 *
 *     node scripts/build_ng_messages.mjs
 *
 * CI re-runs it and fails if the tree is dirty, so generated output cannot drift from source.
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = join(ROOT, 'client/public/locales');
const PROJECT = join(ROOT, 'client_v2/project-ng.inlang');
const OUT = join(ROOT, 'client_v2/locales-ng');

/**
 * The i18next keys the Svelte client's fork-only pages render.
 *
 * Listed explicitly rather than copying the whole catalogue: the React client carries ~770
 * messages and the Svelte pages use a fraction of them, so an allowlist keeps the generated
 * bundle to what is actually reachable. `plural: true` pulls in every CLDR-suffixed variant a
 * locale defines (`_one`, `_few`, `_many`, ...) rather than one fixed pair -- which categories
 * exist is a property of the language, not of the key.
 */
const KEYS = [
	'loading',
	'buttons.refresh',
	'buttons.create',
	'spool.spool',
	'spool.titles.create',
	'spool.fields.material',
	'filament.filament',
	'vendor.vendor',
	'locations.no_location',
	'orders.mark_ordered',
	'low_stock.remaining_left',
	'low_stock.remaining_header',
	'low_stock.section.explicit',
	'low_stock.section.fallback',
	'low_stock.title',
	'low_stock.empty',
	'low_stock.threshold_button',
	'low_stock.threshold_button_value',
	'orders.create_order',
	'orders.create_order_title',
	'orders.create_error',
	'orders.mark_ordered_title',
	'orders.order_date',
	'orders.order_number_field',
	'orders.price_per_unit',
	'orders.quantity',
	'orders.selected_count',
	'orders.shop',
	'orders.shop_placeholder',
	'orders.url',
	'spool.fields.filament',
	// The React page renders no title of its own (the nav says where you are), so this key is
	// unused there -- but it is exactly the nav label the Svelte client needs, already translated.
	'home.home',
	'home.load_error_title',
	'home.load_error_desc',
	'home.welcome',
	'home.description',
	'home.create.spool',
	'home.create.filament',
	'home.create.vendor',
	'home.kpi.this_month',
	'home.kpi.top',
	{ key: 'home.kpi.materials', plural: true },
	'home.total_weight',
	'home.total_value',
	'home.low_stock',
	'home.all_stocked',
	'home.all_spools',
	'home.no_spools',
	'home.by_material',
	'home.by_vendor',
	'home.by_location',
	'home.recently_used',
	'home.no_recent',
	'home.gathering_dust',
	'home.no_stale',
	'home.never_used',
	'home.usage.tab',
	'home.usage.loading',
	'home.usage.empty',
	'home.usage.bucket.day',
	'home.usage.bucket.week',
	'home.usage.bucket.month',
	'home.usage.bucket.year',
];

/** Flatten nested i18next JSON to dotted keys. */
function flatten(obj, prefix = '', out = {}) {
	for (const [k, v] of Object.entries(obj)) {
		const path = prefix ? `${prefix}.${k}` : k;
		if (v && typeof v === 'object' && !Array.isArray(v)) flatten(v, path, out);
		else if (typeof v === 'string') out[path] = v;
	}
	return out;
}

/** `some.key` -> `some_key`. Dots are the character inlang ids disallow. */
const toId = (key) => key.replace(/\./g, '_');

/**
 * i18next spells interpolation `{{name}}`; plugin-message-format spells it `{name}`.
 *
 * Anything left holding a brace after the rewrite is a literal brace in the translation, which
 * message-format would read as an unresolvable placeholder. Fail loudly instead of shipping a
 * label that renders as broken syntax in one language only.
 */
function convertPlaceholders(value, key, locale) {
	const converted = value.replace(/\{\{(\w+)\}\}/g, '{$1}');
	const leftovers = converted.replace(/\{\w+\}/g, '');
	if (leftovers.includes('{') || leftovers.includes('}')) {
		throw new Error(`${locale}: ${key} has a literal brace that cannot be converted: ${value}`);
	}
	return converted;
}

const locales = JSON.parse(readFileSync(join(PROJECT, 'settings.json'), 'utf8')).locales;
mkdirSync(OUT, { recursive: true });

const missingReport = [];
for (const locale of locales) {
	const flat = flatten(JSON.parse(readFileSync(join(SRC, locale, 'common.json'), 'utf8')));
	const messages = { $schema: 'https://inlang.com/schema/inlang-message-format' };
	const missing = [];

	for (const entry of KEYS) {
		const key = typeof entry === 'string' ? entry : entry.key;
		const wanted =
			typeof entry === 'string'
				? [key]
				: Object.keys(flat).filter((k) => k === key || k.startsWith(`${key}_`));
		if (wanted.length === 0) missing.push(key);
		for (const k of wanted) {
			const value = flat[k];
			// Weblate writes an empty string for an untranslated key. Omitting it entirely lets
			// Paraglide fall back to the base locale instead of rendering a blank label.
			if (typeof value !== 'string' || value === '') {
				if (k === key) missing.push(k);
				continue;
			}
			messages[toId(k)] = convertPlaceholders(value, k, locale);
		}
	}

	if (locale === 'en' && missing.length) {
		throw new Error(`en is the base locale and is missing: ${missing.join(', ')}`);
	}
	if (missing.length) missingReport.push(`${locale}: ${missing.length} untranslated`);
	// Tab-indented to match client_v2's prettier config (useTabs), so `npm run lint` passes
	// over the generated catalogue rather than needing it added to .prettierignore.
	writeFileSync(join(OUT, `${locale}.json`), JSON.stringify(messages, null, '\t') + '\n');
}

const enCount = Object.keys(JSON.parse(readFileSync(join(OUT, 'en.json'), 'utf8'))).length - 1;
console.log(`Wrote ${locales.length} locales, ${enCount} messages each (en).`);
if (missingReport.length) {
	console.log(`Falling back to en where untranslated:\n  ${missingReport.join('\n  ')}`);
}
