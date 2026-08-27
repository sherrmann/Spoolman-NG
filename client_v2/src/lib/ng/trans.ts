/**
 * A tiny reader for the React catalogue's one `<Trans>`-style message (#123 follow-up).
 *
 * `help.description` is a single string carrying markup:
 *
 *     <p>To add a new spool, start by creating a
 *     <filamentCreateLink>Filament</filamentCreateLink> object...</p>
 *
 * i18next renders that through react-i18next's <Trans>, which substitutes a real component for
 * each tag. Paraglide has no equivalent, so transcribed as-is the string would render with its
 * tags visible as text. The alternative -- splitting the copy into a key per sentence -- cannot
 * express a link INSIDE a sentence without either fragmenting it (which reads badly and breaks
 * word order in other languages) or abandoning the 32 existing translations of this text.
 *
 * So it is parsed instead, into a shape the page renders with ordinary Svelte markup. No
 * `{@html}` anywhere: the output is data, and the page builds real elements from it, so a
 * translation can never inject markup even in principle. That is the whole reason this returns
 * a tree rather than an HTML string.
 *
 * Deliberately NOT a general HTML parser. It understands exactly the shape this one message
 * has -- a sequence of blocks, each holding text and single-level inline links -- and anything
 * it does not recognise it emits as literal text rather than guessing. A translation that
 * mangles a tag then shows a stray `<p>` to the reader, which is visible and reportable;
 * silently dropping it would not be.
 */

/** A run of plain text, or a piece of text wrapped in a named inline tag (a link). */
export type Inline = { kind: 'text'; text: string } | { kind: 'tag'; name: string; text: string };

/** One block: a named container with inline content, or a self-closing placeholder. */
export type Block = { kind: 'block'; name: string; inline: Inline[] } | { kind: 'void'; name: string };

const BLOCK_RE = /<(\w+)>([\s\S]*?)<\/\1>|<(\w+)\s*\/>/g;
const INLINE_RE = /<(\w+)>([\s\S]*?)<\/\1>/g;

/** Split a block's contents into plain runs and single-level tagged runs. */
function parseInline(source: string): Inline[] {
	const out: Inline[] = [];
	let last = 0;
	for (const match of source.matchAll(INLINE_RE)) {
		const [whole, name, text] = match;
		const start = match.index;
		if (start > last) out.push({ kind: 'text', text: source.slice(last, start) });
		out.push({ kind: 'tag', name, text });
		last = start + whole.length;
	}
	if (last < source.length) out.push({ kind: 'text', text: source.slice(last) });
	return out.filter((n) => n.kind === 'tag' || n.text !== '');
}

/**
 * Parse a `<Trans>`-style message into blocks.
 *
 * Text sitting outside any block still comes through, as an unnamed block, so a translation
 * that forgets to wrap a paragraph loses its styling but never its words.
 */
export function parseTrans(source: string): Block[] {
	const out: Block[] = [];
	let last = 0;
	for (const match of source.matchAll(BLOCK_RE)) {
		const [whole, name, body, voidName] = match;
		const start = match.index;
		const between = source.slice(last, start).trim();
		if (between) out.push({ kind: 'block', name: '', inline: parseInline(between) });
		if (voidName) out.push({ kind: 'void', name: voidName });
		else out.push({ kind: 'block', name, inline: parseInline(body) });
		last = start + whole.length;
	}
	const tail = source.slice(last).trim();
	if (tail) out.push({ kind: 'block', name: '', inline: parseInline(tail) });
	return out;
}
