/**
 * Incremental Server-Sent Events parsing, for `POST /ai/chat`.
 *
 * Written rather than reached for: `EventSource` only issues GET requests and cannot carry a
 * body, and the chat protocol posts the whole transcript every turn (see $lib/ng/aiChat). So
 * the stream arrives through `fetch` as raw bytes, and something has to turn those into frames.
 *
 * The reason this is a module with its own tests rather than a loop inside the component: a
 * network chunk has nothing to do with a frame boundary. A single `data:` line can arrive in
 * three pieces, two frames can arrive in one chunk, and a parser that assumes otherwise works
 * perfectly against a fast local server and drops the end of a sentence over a real connection.
 * That failure is invisible in a browser and obvious in a unit test.
 *
 * Follows the WHATWG event-stream rules where they matter here: `\r\n`, `\r` and `\n` all end a
 * line; one optional space after the colon is stripped; multiple `data:` lines in a frame join
 * with a newline; a line starting `:` is a comment (proxies send these as keep-alives) and a
 * frame carrying no data is not dispatched.
 */

export interface SseFrame {
	/** The `event:` name, or 'message' when the frame omits one, per the spec's default. */
	event: string;
	/** The joined `data:` payload, still a string -- decoding is the caller's business. */
	data: string;
}

/**
 * A parser fed arbitrary string chunks, returning whatever frames each chunk completed.
 *
 * Stateful by necessity: the tail of a chunk is usually half a frame, and it has to be held
 * until the rest arrives. Callers should treat anything left over at end of stream as
 * incomplete and discard it -- a truncated frame is a broken connection, not a short message.
 */
export function createSseParser(): { push(chunk: string): SseFrame[] } {
	let buffer = '';

	return {
		push(chunk: string): SseFrame[] {
			buffer += chunk;
			const frames: SseFrame[] = [];

			// A blank line terminates a frame. Normalising line endings first keeps the split
			// from having to know about three of them.
			buffer = buffer.replace(/\r\n|\r/g, '\n');

			let sep = buffer.indexOf('\n\n');
			while (sep !== -1) {
				const raw = buffer.slice(0, sep);
				buffer = buffer.slice(sep + 2);
				const frame = parseFrame(raw);
				if (frame !== null) frames.push(frame);
				sep = buffer.indexOf('\n\n');
			}
			return frames;
		}
	};
}

function parseFrame(raw: string): SseFrame | null {
	let event = 'message';
	const data: string[] = [];

	for (const line of raw.split('\n')) {
		// A comment line. Keep-alives arrive this way and must not become empty frames.
		if (line.startsWith(':')) continue;
		const colon = line.indexOf(':');
		const field = colon === -1 ? line : line.slice(0, colon);
		// The spec strips exactly one space after the colon, not all whitespace -- leading
		// spaces beyond the first belong to the value.
		let value = colon === -1 ? '' : line.slice(colon + 1);
		if (value.startsWith(' ')) value = value.slice(1);

		if (field === 'event') event = value;
		else if (field === 'data') data.push(value);
		// `id` and `retry` are meaningful to EventSource's reconnection, which this has none of.
	}

	// A frame with no data line at all carries nothing to act on.
	if (data.length === 0) return null;
	return { event, data: data.join('\n') };
}
