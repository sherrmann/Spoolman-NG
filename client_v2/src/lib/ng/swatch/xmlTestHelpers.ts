// Test-only support for the ported threeMf.test.ts and styles.test.ts.
//
// The classic client's tests parse the generated 3MF model XML with the
// browser's `DOMParser` (jsdom in its vitest config). client_v2's vitest runs
// with `environment: 'node'` and no jsdom/DOMParser polyfill dependency, and
// this port may not add one. Since the XML we generate (threeMf.ts) is
// entirely our own, well-formed output — no CDATA, comments, or unescaped
// entities — a small hand-rolled parser covering just the DOM surface the
// ported tests use (getAttribute, textContent, localName/namespaceURI,
// getElementsByTagName(NS), firstElementChild/nextElementSibling) is enough
// to keep those tests byte-for-byte equivalent in what they assert.

export class XmlElement {
	readonly tagName: string;
	readonly localName: string;
	readonly namespaceURI: string | null;
	readonly children: XmlElement[] = [];
	parentEl: XmlElement | null = null;
	/** Namespace prefix ("" = default) -> URI, in scope at this element (own + inherited). */
	readonly nsContext: Map<string, string>;
	private readonly attributes: Map<string, string>;
	private readonly textParts: string[] = [];

	constructor(
		tagName: string,
		localName: string,
		namespaceURI: string | null,
		attributes: Map<string, string>,
		nsContext: Map<string, string>
	) {
		this.tagName = tagName;
		this.localName = localName;
		this.namespaceURI = namespaceURI;
		this.attributes = attributes;
		this.nsContext = nsContext;
	}

	addText(text: string): void {
		this.textParts.push(text);
	}

	getAttribute(name: string): string | null {
		return this.attributes.has(name) ? (this.attributes.get(name) as string) : null;
	}

	get textContent(): string {
		return this.textParts.join('') + this.children.map((c) => c.textContent).join('');
	}

	get firstElementChild(): XmlElement | null {
		return this.children[0] ?? null;
	}

	get nextElementSibling(): XmlElement | null {
		if (!this.parentEl) return null;
		const index = this.parentEl.children.indexOf(this);
		return this.parentEl.children[index + 1] ?? null;
	}

	getElementsByTagName(name: string): XmlElement[] {
		const result: XmlElement[] = [];
		const visit = (el: XmlElement) => {
			for (const child of el.children) {
				if (child.tagName === name) result.push(child);
				visit(child);
			}
		};
		visit(this);
		return result;
	}

	getElementsByTagNameNS(namespace: string, localName: string): XmlElement[] {
		const result: XmlElement[] = [];
		const visit = (el: XmlElement) => {
			for (const child of el.children) {
				if (child.localName === localName && child.namespaceURI === namespace) result.push(child);
				visit(child);
			}
		};
		visit(this);
		return result;
	}
}

export class XmlDocument {
	private readonly root: XmlElement;

	constructor(root: XmlElement) {
		this.root = root;
	}

	get documentElement(): XmlElement {
		return this.root.children[0];
	}

	getElementsByTagName(name: string): XmlElement[] {
		return this.root.getElementsByTagName(name);
	}

	getElementsByTagNameNS(namespace: string, localName: string): XmlElement[] {
		return this.root.getElementsByTagNameNS(namespace, localName);
	}
}

const ENTITIES: Record<string, string> = {
	amp: '&',
	lt: '<',
	gt: '>',
	quot: '"',
	apos: "'"
};

/** Thrown for input DOMParser would report as a parsererror, so a malformed file fails its test. */
export class XmlParseError extends Error {}

// An `&` that does not start one of these is not well-formed XML.
const BARE_AMPERSAND = /&(?!(?:#\d+|#x[0-9a-fA-F]+|amp|lt|gt|quot|apos);)/;

function decodeEntities(text: string): string {
	if (BARE_AMPERSAND.test(text)) throw new XmlParseError(`Unescaped '&' in ${JSON.stringify(text)}`);
	return text.replace(/&(#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);/g, (whole, entity: string) => {
		if (entity[0] === '#') {
			const codePoint =
				entity[1] === 'x' || entity[1] === 'X'
					? parseInt(entity.slice(2), 16)
					: parseInt(entity.slice(1), 10);
			return Number.isNaN(codePoint) ? whole : String.fromCodePoint(codePoint);
		}
		return ENTITIES[entity] ?? whole;
	});
}

const ATTRIBUTE_RE = /([a-zA-Z_:][-\w:.]*)\s*=\s*"([^"]*)"/g;

/**
 * Parse a small, self-produced XML document. Not a general XML parser: it
 * assumes double-quoted attribute values and no CDATA, comments, or DOCTYPE
 * content beyond what `<!...>`/`<?...?>` skipping covers. It is strict where
 * the generator could go wrong -- mismatched or unclosed tags, an unescaped
 * `&` or `<`, stray text inside a tag -- and throws XmlParseError there, as
 * DOMParser would produce a parsererror, so a regression fails its test.
 */
export function parseXml(text: string): XmlDocument {
	const root = new XmlElement('#document', '#document', null, new Map(), new Map());
	const stack: XmlElement[] = [root];
	let i = 0;
	while (i < text.length) {
		const lt = text.indexOf('<', i);
		if (lt === -1) break;
		if (lt > i) {
			const chunk = text.slice(i, lt);
			if (stack.length > 0) stack[stack.length - 1].addText(decodeEntities(chunk));
		}
		if (text[lt + 1] === '?') {
			const end = text.indexOf('?>', lt);
			i = end === -1 ? text.length : end + 2;
			continue;
		}
		if (text[lt + 1] === '!') {
			const end = text.indexOf('>', lt);
			i = end === -1 ? text.length : end + 1;
			continue;
		}
		const gt = text.indexOf('>', lt);
		if (gt === -1) throw new XmlParseError('Unterminated tag');
		const tagContent = text.slice(lt + 1, gt);
		if (tagContent.startsWith('/')) {
			const name = tagContent.slice(1).trim();
			const open = stack[stack.length - 1];
			if (stack.length < 2 || open.tagName !== name) {
				throw new XmlParseError(`Closing </${name}> does not match <${open.tagName}>`);
			}
			stack.pop();
			i = gt + 1;
			continue;
		}
		const selfClosing = tagContent.endsWith('/');
		const inner = selfClosing ? tagContent.slice(0, -1) : tagContent;
		const spaceIndex = inner.search(/\s/);
		const tagName = (spaceIndex === -1 ? inner : inner.slice(0, spaceIndex)).trim();
		const attrsStr = spaceIndex === -1 ? '' : inner.slice(spaceIndex);
		const attributes = new Map<string, string>();
		let match: RegExpExecArray | null;
		ATTRIBUTE_RE.lastIndex = 0;
		while ((match = ATTRIBUTE_RE.exec(attrsStr))) {
			if (match[2].includes('<')) throw new XmlParseError(`Unescaped '<' in attribute ${match[1]}`);
			attributes.set(match[1], decodeEntities(match[2]));
		}
		if (attrsStr.replace(ATTRIBUTE_RE, '').trim() !== '') {
			throw new XmlParseError(`Malformed attributes in <${tagName}>`);
		}
		const colonIndex = tagName.indexOf(':');
		const prefix = colonIndex === -1 ? null : tagName.slice(0, colonIndex);
		const localName = colonIndex === -1 ? tagName : tagName.slice(colonIndex + 1);
		const parent = stack[stack.length - 1];
		const nsContext = new Map<string, string>(parent.nsContext); // "" = default namespace
		for (const [name, value] of attributes) {
			if (name === 'xmlns') nsContext.set('', value);
			else if (name.startsWith('xmlns:')) nsContext.set(name.slice(6), value);
		}
		const namespaceURI = prefix === null ? (nsContext.get('') ?? null) : (nsContext.get(prefix) ?? null);
		const element = new XmlElement(tagName, localName, namespaceURI, attributes, nsContext);
		element.parentEl = parent;
		parent.children.push(element);
		if (!selfClosing) stack.push(element);
		i = gt + 1;
	}
	if (stack.length !== 1) throw new XmlParseError(`Unclosed <${stack[stack.length - 1].tagName}>`);
	return new XmlDocument(root);
}
