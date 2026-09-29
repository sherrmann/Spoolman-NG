/**
 * Spoolman NG fork addition: the fork's own Svelte styles keep to upstream's design language.
 *
 * The oracle is upstream's stylesheets themselves, read at test time, not a list copied out of
 * them: every vendored component's `<style>` block is parsed, and the fork's components may only
 * use what upstream uses -- the same font weights, type sizes inside upstream's range, the same
 * raw colour literals, upstream's section-label style for uppercase text, and no effects upstream
 * never uses (hover lifts, negative tracking). When a subtree pull changes upstream's vocabulary
 * the rules move with it, and a fork page that no longer matches fails here, naming the rule.
 *
 * Fork-owned files are the ones docs/upstream/client-v2-fork-additions.md lists as additions.
 * Upstream files the fork edits (Tier 1/2) count as upstream: their styles are upstream's.
 */
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = path.resolve(__dirname, '../..');

const FORK_PATH =
	/^(lib\/ng\/|routes\/(home|lowstock|orders|locations|location\/show|calibration|help)\/|routes\/\+error\.svelte$)/;

interface Rule {
	file: string;
	selector: string;
	decls: Map<string, string>;
}

function svelteFiles(dir: string): string[] {
	return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
		const full = path.join(dir, e.name);
		if (e.isDirectory()) return e.name.startsWith('paraglide') ? [] : svelteFiles(full);
		return e.name.endsWith('.svelte') ? [full] : [];
	});
}

/** Flat rules from a component's style block. Nested at-rules (@media) contribute their inner
 *  rules; the at-rule itself is dropped, which is all these checks need. */
function rulesOf(file: string): Rule[] {
	const src = readFileSync(file, 'utf8');
	const style = /<style[^>]*>([\s\S]*?)<\/style>/.exec(src)?.[1];
	if (!style) return [];
	const css = style.replace(/\/\*[\s\S]*?\*\//g, '');
	const rel = path.relative(SRC, file).split(path.sep).join('/');
	const rules: Rule[] = [];
	for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
		const decls = new Map<string, string>();
		for (const d of m[2].matchAll(/([a-z-]+)\s*:\s*([^;]+);?/g)) decls.set(d[1], d[2].trim());
		rules.push({ file: rel, selector: m[1].trim().replace(/\s+/g, ' '), decls });
	}
	return rules;
}

const all = svelteFiles(SRC).flatMap(rulesOf);
const upstream = all.filter((r) => !FORK_PATH.test(r.file));
const fork = all.filter((r) => FORK_PATH.test(r.file));

const where = (r: Rule, prop: string) => `${r.file} ${r.selector} { ${prop}: ${r.decls.get(prop)} }`;
const px = (v: string) => (/^(\d+(?:\.\d+)?)px$/.exec(v) ? Number(v.slice(0, -2)) : null);
const em = (v: string) => (/^(-?\d*\.?\d+)em$/.exec(v) ? Number(v.slice(0, -2)) : null);
const isUppercase = (r: Rule) => r.decls.get('text-transform') === 'uppercase';

/** Raw colour literals (hex, rgb/rgba, hsl) written into a declaration, lower-cased. */
function colourLiterals(value: string): string[] {
	return (value.match(/#[0-9a-f]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)/gi) ?? []).map((c) =>
		c.toLowerCase().replace(/\s+/g, '')
	);
}

function valuesOf(rules: Rule[], prop: string): Set<string> {
	return new Set(rules.map((r) => r.decls.get(prop)).filter((v): v is string => v !== undefined));
}

describe('the fork styles its pages in upstream design language', () => {
	it('finds both sides to compare', () => {
		// A moved directory would otherwise make every check below pass vacuously.
		expect(upstream.length).toBeGreaterThan(500);
		expect(fork.length).toBeGreaterThan(500);
	});

	it('uses only font weights upstream uses', () => {
		const allowed = valuesOf(upstream, 'font-weight');
		const bad = fork.filter((r) => r.decls.has('font-weight') && !allowed.has(r.decls.get('font-weight')!));
		expect(
			bad.map((r) => where(r, 'font-weight')),
			`upstream uses ${[...allowed].join(', ')}`
		).toEqual([]);
	});

	it('keeps type sizes inside upstream range', () => {
		const sizes = [...valuesOf(upstream, 'font-size')].map(px).filter((n): n is number => n !== null);
		const [min, max] = [Math.min(...sizes), Math.max(...sizes)];
		const bad = fork.filter((r) => {
			const n = px(r.decls.get('font-size') ?? '');
			return n !== null && (n < min || n > max);
		});
		expect(
			bad.map((r) => where(r, 'font-size')),
			`upstream sizes run ${min}px-${max}px`
		).toEqual([]);
	});

	it('writes colours as tokens, except the literals upstream itself writes', () => {
		// White text on a filled button and the modal scrim are the usual literals; anything
		// else must be a var(--...) token, so both themes resolve it.
		const allowed = new Set(upstream.flatMap((r) => [...r.decls.values()].flatMap(colourLiterals)));
		const bad = fork.flatMap((r) =>
			[...r.decls.entries()]
				.filter(([, v]) => colourLiterals(v).some((c) => !allowed.has(c)))
				.map(([p]) => where(r, p))
		);
		expect(bad).toEqual([]);
	});

	it('refers only to tokens that exist', () => {
		// A misspelt or invented token (`--bg-elevated`, `--warning`) silently resolves to its
		// fallback, or to nothing, in both themes. Defined means declared in app.css or by any
		// component (a style block, or a `style:--x` / `style="--x:` on an element).
		const sources = [
			readFileSync(path.join(SRC, 'app.css'), 'utf8'),
			...svelteFiles(SRC).map((f) => readFileSync(f, 'utf8'))
		];
		const defined = new Set(
			sources.flatMap((s) => [...s.matchAll(/(?:^|[\s;{"'(:])(--[a-z0-9-]+)\s*[:=]/g)].map((m) => m[1]))
		);
		const bad = fork.flatMap((r) =>
			[...r.decls.entries()].flatMap(([p, v]) =>
				[...v.matchAll(/var\((--[a-z0-9-]+)/g)]
					.filter((m) => !defined.has(m[1]))
					.map((m) => `${where(r, p)} -- ${m[1]} is not defined`)
			)
		);
		expect(bad).toEqual([]);
	});

	it('styles uppercase labels as upstream section labels', () => {
		// SectionLabel.svelte: 11px, uppercase, 0.07em tracking, --text-dim, normal weight.
		// Upstream never makes one bold (700), faint, or tracks it wider than it does itself.
		const upper = upstream.filter(isUppercase);
		const maxTrack = Math.max(...upper.map((r) => em(r.decls.get('letter-spacing') ?? '') ?? 0));
		const problems = fork.filter(isUppercase).flatMap((r) => {
			const out: string[] = [];
			const weight = Number(r.decls.get('font-weight') ?? 400);
			if (weight >= 700 && !/\bh[1-6]\b/.test(r.selector)) out.push(where(r, 'font-weight'));
			const track = em(r.decls.get('letter-spacing') ?? '');
			if (track !== null && track > maxTrack) out.push(where(r, 'letter-spacing'));
			if (r.decls.get('color')?.includes('--text-faint')) out.push(where(r, 'color'));
			return out;
		});
		expect(problems, `upstream tracks uppercase labels at most ${maxTrack}em`).toEqual([]);
	});

	it('uses no effect upstream never uses', () => {
		const hoverMoves = (r: Rule) =>
			/:hover/.test(r.selector) && /translate/.test(r.decls.get('transform') ?? '');
		const negativeTracking = (r: Rule) => (em(r.decls.get('letter-spacing') ?? '') ?? 0) < 0;
		const fonts = (r: Rule) => {
			const f = r.decls.get('font-family');
			return f !== undefined && !/^(inherit|var\(--font-(sans|mono)[^)]*\))$/.test(f);
		};
		for (const [name, test] of [
			['a hover that moves the element', hoverMoves],
			['negative letter-spacing', negativeTracking],
			['a font outside the --font-sans/--font-mono tokens', fonts]
		] as const) {
			// Only enforced while upstream itself has none; if upstream adopts one, so may we.
			if (upstream.some(test)) continue;
			expect(
				fork.filter(test).map((r) => `${r.file} ${r.selector}`),
				`${name}: upstream has none`
			).toEqual([]);
		}
	});
});
