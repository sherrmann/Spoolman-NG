import { describe, expect, it } from 'vitest';
import { createSseParser } from './sse';

/**
 * These tests are mostly about chunk boundaries, because that is the only thing hard about
 * parsing this format and the only thing a browser will not show you: a parser that assumes a
 * chunk is a frame works flawlessly against a local server and silently truncates over a real
 * connection.
 */
describe('createSseParser', () => {
	it('reads a complete frame', () => {
		const p = createSseParser();
		expect(p.push('event: message\ndata: {"content":"hi"}\n\n')).toEqual([
			{ event: 'message', data: '{"content":"hi"}' }
		]);
	});

	it('returns nothing until the terminating blank line arrives', () => {
		// The frame is entirely present except its terminator. Emitting it here would mean
		// acting on half a message whenever a chunk happened to land on a newline.
		const p = createSseParser();
		expect(p.push('event: message\ndata: {"content":"hi"}\n')).toEqual([]);
		expect(p.push('\n')).toEqual([{ event: 'message', data: '{"content":"hi"}' }]);
	});

	it('reassembles a frame split anywhere, including mid-value', () => {
		const p = createSseParser();
		expect(p.push('event: mes')).toEqual([]);
		expect(p.push('sage\ndata: {"con')).toEqual([]);
		expect(p.push('tent":"hello"}')).toEqual([]);
		expect(p.push('\n\n')).toEqual([{ event: 'message', data: '{"content":"hello"}' }]);
	});

	it('returns every frame when several arrive in one chunk', () => {
		const p = createSseParser();
		expect(p.push('event: tool\ndata: {"name":"find_spools"}\n\nevent: done\ndata: {}\n\n')).toEqual([
			{ event: 'tool', data: '{"name":"find_spools"}' },
			{ event: 'done', data: '{}' }
		]);
	});

	it('carries a partial trailing frame into the next chunk', () => {
		// The commonest real shape: one whole frame plus the start of the next.
		const p = createSseParser();
		expect(p.push('event: tool\ndata: {}\n\nevent: mes')).toEqual([{ event: 'tool', data: '{}' }]);
		expect(p.push('sage\ndata: {"content":"x"}\n\n')).toEqual([
			{ event: 'message', data: '{"content":"x"}' }
		]);
	});

	it('accepts CRLF, which a proxy may introduce', () => {
		const p = createSseParser();
		expect(p.push('event: done\r\ndata: {}\r\n\r\n')).toEqual([{ event: 'done', data: '{}' }]);
	});

	it('defaults a frame with no event name to "message", per the spec', () => {
		const p = createSseParser();
		expect(p.push('data: {"content":"x"}\n\n')).toEqual([{ event: 'message', data: '{"content":"x"}' }]);
	});

	it('strips exactly one space after the colon, not all of it', () => {
		// The second space belongs to the value. Trimming it would corrupt any payload that
		// legitimately starts with whitespace.
		const p = createSseParser();
		expect(p.push('data:  x\n\n')).toEqual([{ event: 'message', data: ' x' }]);
	});

	it('joins multiple data lines with a newline', () => {
		const p = createSseParser();
		expect(p.push('event: message\ndata: one\ndata: two\n\n')).toEqual([
			{ event: 'message', data: 'one\ntwo' }
		]);
	});

	it('ignores comment lines, which arrive as keep-alives', () => {
		// A proxy sends `: ping` to hold the connection open. Turning that into an empty frame
		// would make the UI act on nothing.
		const p = createSseParser();
		expect(p.push(': ping\n\nevent: done\ndata: {}\n\n')).toEqual([{ event: 'done', data: '{}' }]);
	});

	it('drops a frame carrying no data line at all', () => {
		const p = createSseParser();
		expect(p.push('event: done\n\n')).toEqual([]);
	});

	it('holds an unterminated final frame rather than emitting it', () => {
		// A truncated frame means a broken connection, not a short message. Emitting it would
		// turn a dropped stream into a plausible-looking half answer.
		const p = createSseParser();
		expect(p.push('event: message\ndata: {"content":"trunc')).toEqual([]);
	});
});
