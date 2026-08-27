import { describe, expect, it } from 'vitest';
import {
	applyChatEvent,
	decodeChatFrame,
	initialChatState,
	startDecision,
	startTurn,
	type ChatState
} from './aiChat';

const ev = (event: string, data: Record<string, unknown>) =>
	({ event, data }) as Parameters<typeof applyChatEvent>[1];

/** Fold a whole turn's worth of frames, the way a real stream arrives. */
function run(state: ChatState, frames: [string, Record<string, unknown>][]): ChatState {
	return frames.reduce((s, [e, d]) => applyChatEvent(s, ev(e, d)), state);
}

describe('a plain question and answer', () => {
	it('records the user turn and puts the reply in both the transcript and the bubbles', () => {
		// The reply has to reach the TRANSCRIPT as well as the screen: the next turn re-sends
		// the whole thing, and an assistant whose own words are missing repeats itself.
		let s = startTurn(initialChatState(), 'how much PETG?');
		expect(s.status).toBe('streaming');
		s = run(s, [
			['message', { content: 'About 1.2 kg.' }],
			['done', {}]
		]);

		expect(s.status).toBe('idle');
		expect(s.messages).toEqual([
			{ role: 'user', content: 'how much PETG?' },
			{ role: 'assistant', content: 'About 1.2 kg.' }
		]);
		expect(s.bubbles).toEqual([
			{ kind: 'user', text: 'how much PETG?' },
			{ kind: 'assistant', text: 'About 1.2 kg.' }
		]);
	});

	it('shows a read tool without adding it to the transcript', () => {
		// The server already appended the tool result to the convo it hands back. Adding our
		// own entry would duplicate it and desync the tool-call/tool-result pairing.
		let s = startTurn(initialChatState(), 'what is low?');
		s = run(s, [
			['tool', { name: 'find_spools', summary: 'Found 3 spool(s).' }],
			['message', { content: 'Three are low.' }],
			['done', {}]
		]);

		expect(s.bubbles[1]).toEqual({
			kind: 'tool',
			name: 'find_spools',
			summary: 'Found 3 spool(s).'
		});
		expect(s.messages).toHaveLength(2); // the user turn and the reply, nothing from the tool
	});
});

describe('a mutation the user has to approve', () => {
	const CARD = {
		tool_call_id: 'call_1',
		tool: 'update_spool',
		title: 'Update spool #4',
		summary: 'Set location to Shelf B',
		before: { location: 'Shelf A' },
		after: { location: 'Shelf B' },
		destructive: false
	};
	// What the server hands back: the convo INCLUDING the assistant's pending tool call.
	const SERVER_CONVO = [
		{ role: 'user', content: 'move spool 4 to shelf B' },
		{ role: 'assistant', tool_calls: [{ id: 'call_1', function: { name: 'update_spool' } }] }
	];

	it('adopts the transcript the confirm frame carries, replacing its own', () => {
		// The most important assertion in this file. That transcript holds the pending tool
		// call the server needs back verbatim to know what the user is saying yes to. Keeping
		// our own copy instead would ask the model to decide again, and the user's approval
		// would land on a mutation nobody previewed.
		let s = startTurn(initialChatState(), 'move spool 4 to shelf B');
		expect(s.messages).toHaveLength(1);

		s = run(s, [
			['confirm', { messages: SERVER_CONVO, cards: [CARD] }],
			['done', {}]
		]);

		expect(s.messages).toEqual(SERVER_CONVO);
		// The server's convo contains the user turn too, so its presence proves nothing. What
		// appending would produce is a SECOND copy of it, and a transcript with the same turn
		// twice is what desyncs the model's tool-call pairing.
		const userTurns = s.messages.filter((msg) => msg.role === 'user');
		expect(userTurns).toHaveLength(1);
	});

	it('stays awaiting a decision after done, because done only closes the stream', () => {
		// `done` ends the HTTP response, not the exchange. Treating it as "turn over" would
		// re-enable the composer and leave the preview stranded.
		let s = startTurn(initialChatState(), 'move it');
		s = run(s, [
			['confirm', { messages: SERVER_CONVO, cards: [CARD] }],
			['done', {}]
		]);

		expect(s.status).toBe('awaiting_confirm');
		expect(s.pending).toEqual([CARD]);
	});

	it('reports what was executed once confirmed', () => {
		let s = startTurn(initialChatState(), 'move it');
		s = run(s, [
			['confirm', { messages: SERVER_CONVO, cards: [CARD] }],
			['done', {}]
		]);
		s = startDecision(s);
		expect(s.status).toBe('streaming');
		expect(s.pending).toEqual([]);

		s = run(s, [
			['executed', { cards: [{ tool: 'update_spool', summary: 'Moved to Shelf B', undo: null }] }],
			['message', { content: 'Done.' }],
			['done', {}]
		]);

		expect(s.status).toBe('idle');
		expect(s.bubbles).toContainEqual({
			kind: 'executed',
			cards: [{ tool: 'update_spool', summary: 'Moved to Shelf B', undo: null }]
		});
	});

	it('records a cancellation rather than silently dropping it', () => {
		// Declining is a decision the user made and should be able to see they made.
		let s = startTurn(initialChatState(), 'delete it');
		s = run(s, [
			['confirm', { messages: SERVER_CONVO, cards: [CARD] }],
			['done', {}]
		]);
		s = run(startDecision(s), [
			['cancelled', {}],
			['done', {}]
		]);

		expect(s.bubbles).toContainEqual({ kind: 'cancelled' });
		expect(s.status).toBe('idle');
	});
});

describe('robustness', () => {
	it('ignores an unknown event rather than throwing', () => {
		// A server that grows a frame type must not break a client that has not learned it.
		const s = run(startTurn(initialChatState(), 'hi'), [
			['reasoning', { text: 'hmm' }],
			['message', { content: 'hello' }],
			['done', {}]
		]);
		expect(s.bubbles).toEqual([
			{ kind: 'user', text: 'hi' },
			{ kind: 'assistant', text: 'hello' }
		]);
	});

	it('drops an empty message instead of rendering a blank bubble', () => {
		const s = run(startTurn(initialChatState(), 'hi'), [
			['message', { content: '' }],
			['done', {}]
		]);
		expect(s.bubbles).toEqual([{ kind: 'user', text: 'hi' }]);
	});

	it('surfaces an error frame and still returns to idle', () => {
		// An error mid-turn must not leave the composer disabled forever.
		const s = run(startTurn(initialChatState(), 'hi'), [
			['error', { message: 'The model timed out.' }],
			['done', {}]
		]);
		expect(s.bubbles).toContainEqual({ kind: 'error', text: 'The model timed out.' });
		expect(s.status).toBe('idle');
	});
});

describe('decodeChatFrame', () => {
	it('decodes a frame', () => {
		expect(decodeChatFrame('message', '{"content":"hi"}')).toEqual({
			event: 'message',
			data: { content: 'hi' }
		});
	});

	it('returns null for malformed JSON, so one bad frame costs only itself', () => {
		expect(decodeChatFrame('message', '{"content":')).toBeNull();
	});

	it('returns null for a non-object payload', () => {
		// `data: "hi"` is valid JSON and not a frame this protocol has any use for.
		expect(decodeChatFrame('message', '"hi"')).toBeNull();
	});
});
