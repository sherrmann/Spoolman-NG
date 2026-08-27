import { describe, it, expect } from 'vitest';
import { parseTrans, type Block } from './trans';

/**
 * The reader for the catalogue's one `<Trans>`-style message.
 *
 * The real input is `help.description`, which exists in 32 translations written by people who
 * are not looking at this parser. So the cases that matter are the ones where a translation is
 * imperfect: a dropped closing tag, reordered links, text left outside a paragraph. None of
 * those may lose the reader's words.
 */

const text = (b: Block) => (b.kind === 'block' ? b.inline.map((i) => i.text).join('') : '');

describe('parsing blocks', () => {
	it('reads a sequence of paragraphs', () => {
		const blocks = parseTrans('<p>One</p><p>Two</p>');
		expect(blocks.map((b) => b.kind === 'block' && b.name)).toEqual(['p', 'p']);
		expect(blocks.map(text)).toEqual(['One', 'Two']);
	});

	it('reads a self-closing placeholder as its own block', () => {
		expect(parseTrans('<p>Before</p><itemsHelp/><p>After</p>')).toEqual([
			{ kind: 'block', name: 'p', inline: [{ kind: 'text', text: 'Before' }] },
			{ kind: 'void', name: 'itemsHelp' },
			{ kind: 'block', name: 'p', inline: [{ kind: 'text', text: 'After' }] }
		]);
	});

	it('keeps the different block names apart', () => {
		const blocks = parseTrans('<title>Help</title><p>Body</p>');
		expect(blocks.map((b) => b.kind === 'block' && b.name)).toEqual(['title', 'p']);
	});
});

describe('parsing inline links', () => {
	it('splits a paragraph into text and named links, in order', () => {
		const [block] = parseTrans('<p>Create a <aLink>Filament</aLink> first.</p>');
		expect(block).toEqual({
			kind: 'block',
			name: 'p',
			inline: [
				{ kind: 'text', text: 'Create a ' },
				{ kind: 'tag', name: 'aLink', text: 'Filament' },
				{ kind: 'text', text: ' first.' }
			]
		});
	});

	it('handles several links in one paragraph', () => {
		const [block] = parseTrans('<p><a>One</a> and <b>Two</b></p>');
		expect(block.kind === 'block' && block.inline.map((i) => i.kind)).toEqual(['tag', 'text', 'tag']);
	});

	it('survives a translation that reorders the links', () => {
		// Word order differs by language; the parser must not assume link N comes at position N.
		const [block] = parseTrans('<p><b>Zwei</b> und <a>Eins</a></p>');
		expect(block.kind === 'block' && block.inline.filter((i) => i.kind === 'tag')).toEqual([
			{ kind: 'tag', name: 'b', text: 'Zwei' },
			{ kind: 'tag', name: 'a', text: 'Eins' }
		]);
	});
});

describe('imperfect translations', () => {
	it('keeps text a translator left outside any block', () => {
		// Losing a sentence silently would be far worse than showing it unstyled.
		const blocks = parseTrans('Loose words <p>In a block</p>');
		expect(blocks.map(text)).toEqual(['Loose words', 'In a block']);
	});

	it('keeps trailing text after the last block', () => {
		expect(parseTrans('<p>First</p>and then some').map(text)).toEqual(['First', 'and then some']);
	});

	it('does not swallow a paragraph whose closing tag is missing', () => {
		// An unclosed tag cannot be matched as a block, so it falls through as literal text --
		// visible and reportable, rather than a silently blank page.
		const blocks = parseTrans('<p>Unclosed');
		expect(blocks.map(text).join('')).toContain('Unclosed');
	});

	it('returns nothing for an empty message rather than an empty block', () => {
		expect(parseTrans('')).toEqual([]);
		expect(parseTrans('   ')).toEqual([]);
	});

	it('leaves an unknown tag to the caller rather than guessing', () => {
		// The page decides what to do with a name it does not recognise; the parser only reports.
		const [block] = parseTrans('<p>See <somethingNew>this</somethingNew></p>');
		expect(block.kind === 'block' && block.inline[1]).toEqual({
			kind: 'tag',
			name: 'somethingNew',
			text: 'this'
		});
	});
});

describe('the real help.description shape', () => {
	const REAL =
		'<title>Help</title><p>Here are some tips.</p><p>Spoolman holds 3 types:</p><itemsHelp/>' +
		"<p>Start by creating a <filamentCreateLink>Filament</filamentCreateLink> object. Once that's done, create a <spoolCreateLink>Spool</spoolCreateLink>.</p>";

	it('yields the blocks the page renders', () => {
		const blocks = parseTrans(REAL);
		expect(blocks.map((b) => (b.kind === 'void' ? `void:${b.name}` : b.name))).toEqual([
			'title',
			'p',
			'p',
			'void:itemsHelp',
			'p'
		]);
	});

	it('exposes both create links with their own labels', () => {
		const blocks = parseTrans(REAL);
		const tags = blocks.flatMap((b) => (b.kind === 'block' ? b.inline : [])).filter((i) => i.kind === 'tag');
		expect(tags).toEqual([
			{ kind: 'tag', name: 'filamentCreateLink', text: 'Filament' },
			{ kind: 'tag', name: 'spoolCreateLink', text: 'Spool' }
		]);
	});

	it('loses none of the prose', () => {
		const rendered = parseTrans(REAL).map(text).join(' ');
		expect(rendered).toContain('Here are some tips.');
		expect(rendered).toContain("Once that's done, create a");
	});
});
