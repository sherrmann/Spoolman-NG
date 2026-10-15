import { describe, expect, it } from 'vitest';
import {
	applyChatEvent,
	decodeChatFrame,
	initialChatState,
	abandonTurn,
	awaitingOutcome,
	isDeciding,
	pairToolCalls,
	restoreChat,
	serialiseChat,
	startDecision,
	startTurn,
	stopTurn,
	type ChatMessage,
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

describe('streamed reply text (#381)', () => {
	it('shows deltas while they arrive and replaces them with the final message', () => {
		let s = startTurn(initialChatState(), 'how much?');
		s = run(s, [
			['delta', { content: 'About ' }],
			['delta', { content: '1.2 kg.' }]
		]);
		expect(s.streaming).toBe('About 1.2 kg.');
		expect(s.bubbles).toHaveLength(1);

		s = run(s, [
			['message', { content: 'About 1.2 kg.' }],
			['done', {}]
		]);
		expect(s.streaming).toBe('');
		expect(s.bubbles.at(-1)).toEqual({ kind: 'assistant', text: 'About 1.2 kg.' });
		// The streamed text never reaches the transcript on its own; only the message does.
		expect(s.messages.filter((m) => m.role === 'assistant')).toHaveLength(1);
	});

	it('drops text streamed before a tool call: the tool event supersedes it', () => {
		let s = startTurn(initialChatState(), 'spools?');
		s = run(s, [
			['delta', { content: 'Let me check. ' }],
			['tool', { name: 'find_spools', summary: 'Found 2 spool(s).' }],
			['delta', { content: 'You have 2.' }],
			['message', { content: 'You have 2.' }],
			['done', {}]
		]);
		expect(s.bubbles.map((b) => b.kind)).toEqual(['user', 'tool', 'assistant']);
		expect(s.bubbles.some((b) => b.kind === 'assistant' && b.text.includes('Let me check'))).toBe(false);
	});

	it('clears streamed text on an error too', () => {
		let s = startTurn(initialChatState(), 'x');
		s = run(s, [
			['delta', { content: 'Half an ans' }],
			['error', { message: 'The AI endpoint stopped part-way through its reply.' }]
		]);
		expect(s.streaming).toBe('');
		expect(s.bubbles.at(-1)?.kind).toBe('error');
	});

	it('ignores deltas when no turn is streaming', () => {
		const s = run(initialChatState(), [['delta', { content: 'stray' }]]);
		expect(s.streaming).toBe('');
	});

	it('keeps the rows, total and usage periods a tool event carries', () => {
		const s = run(startTurn(initialChatState(), 'x'), [
			[
				'tool',
				{
					name: 'find_spools',
					summary: 'Found 7 spool(s).',
					rows: [{ id: 1 }, 'junk', { id: 2 }],
					total: 7,
					filters: { material: 'PLA' }
				}
			],
			[
				'tool',
				{
					name: 'get_usage_stats',
					summary: 's',
					periods: [{ period: '2026-09', consumed_weight: 5, cost: 1 }, {}]
				}
			]
		]);
		expect(s.bubbles[1]).toEqual({
			kind: 'tool',
			name: 'find_spools',
			summary: 'Found 7 spool(s).',
			rows: [{ id: 1 }, { id: 2 }],
			total: 7,
			filters: { material: 'PLA' }
		});
		expect(s.bubbles[2]).toMatchObject({ periods: [{ period: '2026-09', consumed_weight: 5, cost: 1 }] });
	});
});

describe('stopping a turn', () => {
	it('keeps what was streamed as a reply, in the bubbles and the transcript', () => {
		let s = run(startTurn(initialChatState(), 'x'), [['delta', { content: 'Partial answer ' }]]);
		s = stopTurn(s);
		expect(s.status).toBe('idle');
		expect(s.streaming).toBe('');
		expect(s.bubbles.at(-1)).toEqual({ kind: 'assistant', text: 'Partial answer' });
		expect(s.messages.at(-1)).toEqual({ role: 'assistant', content: 'Partial answer' });
	});

	it('just goes idle when nothing was streamed', () => {
		const s = stopTurn(startTurn(initialChatState(), 'x'));
		expect(s.status).toBe('idle');
		expect(s.bubbles).toHaveLength(1);
	});

	it('leaves a pending confirmation alone', () => {
		const s = run(startTurn(initialChatState(), 'delete it'), [
			['confirm', { messages: [{ role: 'user', content: 'delete it' }], cards: [] }],
			['done', {}]
		]);
		expect(stopTurn(s)).toBe(s);
	});
});

describe('keeping a conversation across reloads', () => {
	const settled = () =>
		run(startTurn(initialChatState(), 'how much?'), [
			['message', { content: 'About 1.2 kg.' }],
			['done', {}]
		]);

	it('round-trips a settled conversation', () => {
		const s = settled();
		const back = restoreChat(serialiseChat(s));
		expect(back?.messages).toEqual(s.messages);
		expect(back?.bubbles).toEqual(s.bubbles);
		expect(back?.status).toBe('idle');
	});

	it('does not store a turn that is still streaming, or an empty chat', () => {
		expect(serialiseChat(startTurn(initialChatState(), 'x'))).toBeNull();
		expect(serialiseChat(initialChatState())).toBeNull();
	});

	it('turns a pending confirmation into a cancellation and drops the pending tool calls', () => {
		const pendingTranscript = [
			{ role: 'user', content: 'delete spool 3' },
			{ role: 'assistant', content: null, tool_calls: [{ id: 'c1', function: { name: 'delete_spool' } }] }
		];
		const s = run(startTurn(initialChatState(), 'delete spool 3'), [
			[
				'confirm',
				{
					messages: pendingTranscript,
					cards: [{ tool: 'delete_spool', title: 'Delete', summary: '', before: {}, after: {} }]
				}
			],
			['done', {}]
		]);
		expect(s.status).toBe('awaiting_confirm');

		const back = restoreChat(serialiseChat(s));
		expect(back?.status).toBe('idle');
		expect(back?.pending).toEqual([]);
		expect(back?.bubbles.at(-1)).toEqual({ kind: 'cancelled' });
		expect(back?.messages).toEqual([{ role: 'user', content: 'delete spool 3' }]);
	});

	it('starts a trimmed transcript at a user turn, so no tool result loses its call', () => {
		let s = settled();
		const filler = Array.from({ length: 45 }, (_, i) => [
			{ role: 'user', content: `q${i}` },
			{ role: 'assistant', content: null, tool_calls: [{ id: `c${i}` }] },
			{ role: 'tool', tool_call_id: `c${i}`, content: '{}' },
			{ role: 'assistant', content: `a${i}` }
		]).flat();
		s = { ...s, messages: filler };
		const back = restoreChat(serialiseChat(s));
		expect(back!.messages.length).toBeLessThanOrEqual(40);
		expect(back!.messages[0].role).toBe('user');
	});

	it('rejects junk', () => {
		expect(restoreChat(null)).toBeNull();
		expect(restoreChat('not json')).toBeNull();
		expect(restoreChat('{"messages": 1, "bubbles": []}')).toBeNull();
		expect(restoreChat('{"messages": [], "bubbles": [1, null]}')).toBeNull();
	});
});

describe('fixes from review', () => {
	const pendingWrite = (extra: ChatMessage[] = []) => [
		{ role: 'user', content: 'move spool 3 and tell me what is on shelf A' },
		{
			role: 'assistant',
			content: null,
			tool_calls: [
				{ id: 'r1', function: { name: 'find_spools' } },
				{ id: 'w1', function: { name: 'update_spool' } }
			]
		},
		{ role: 'tool', tool_call_id: 'r1', content: '{}' },
		...extra
	];
	const confirmed = () =>
		run(startTurn(initialChatState(), 'move spool 3'), [
			[
				'confirm',
				{
					messages: pendingWrite(),
					cards: [{ tool: 'update_spool', title: 'Move', summary: '', before: {}, after: {} }]
				}
			],
			['done', {}]
		]);

	it('pairs every tool call with its result and drops the unanswered ones', () => {
		expect(pairToolCalls(pendingWrite())).toEqual([pendingWrite()[0]]);
		const answered = pendingWrite([{ role: 'tool', tool_call_id: 'w1', content: '{}' }]);
		expect(pairToolCalls(answered)).toEqual(answered);
	});

	it('keeps the text of an assistant turn whose calls are dropped', () => {
		const out = pairToolCalls([
			{ role: 'user', content: 'q' },
			{ role: 'assistant', content: 'Moving it now.', tool_calls: [{ id: 'x' }] }
		]);
		expect(out.at(-1)).toEqual({ role: 'assistant', content: 'Moving it now.' });
	});

	it('sends a valid history after a confirmed write, whose result the client never gets', () => {
		let s = startDecision(confirmed());
		s = run(s, [
			['executed', { cards: [{ tool: 'update_spool', summary: 'Moved spool 3.' }] }],
			['message', { content: 'Done.' }],
			['done', {}]
		]);
		s = startTurn(s, 'thanks, and spool 4?');
		const unanswered = s.messages.filter(
			(m) =>
				Array.isArray(m.tool_calls) && !s.messages.some((r) => r.role === 'tool' && r.tool_call_id === 'w1')
		);
		expect(unanswered).toEqual([]);
		expect(s.messages.at(-1)).toEqual({ role: 'user', content: 'thanks, and spool 4?' });
	});

	it('restores a mixed read-and-write round without the unanswered write call', () => {
		const back = restoreChat(serialiseChat(confirmed()));
		expect(back?.messages).toEqual([pendingWrite()[0]]);
		expect(back?.bubbles.at(-1)).toEqual({ kind: 'cancelled' });
	});

	it('does not let Stop hide a decision in flight', () => {
		const s = startDecision(confirmed());
		expect(isDeciding(s)).toBe(true);
		expect(stopTurn(s)).toBe(s);
	});

	it('restores a decision sent but never answered as of unknown outcome, not cancelled', () => {
		const back = restoreChat(serialiseChat(startDecision(confirmed())));
		expect(back?.bubbles.at(-1)).toEqual({ kind: 'unknown' });
		expect(back?.status).toBe('idle');
	});

	it('does not bring back Undo buttons', () => {
		const s = run(startTurn(initialChatState(), 'x'), [
			[
				'executed',
				{
					cards: [
						{
							tool: 'consume',
							summary: 'Used 100 g.',
							undo: { tool: 'set_spool_used_weight', args: { used_weight_g: 200 } }
						}
					]
				}
			],
			['message', { content: 'Done.' }],
			['done', {}]
		]);
		const back = restoreChat(serialiseChat(s));
		const executed = back?.bubbles.find((b) => b.kind === 'executed');
		expect(executed).toEqual({
			kind: 'executed',
			cards: [{ tool: 'consume', summary: 'Used 100 g.', undo: null }]
		});
	});
});

describe('fixes from the second review', () => {
	it('pairs calls with the results right after them, so a reused id cannot vouch for a later call', () => {
		const messages: ChatMessage[] = [
			{ role: 'user', content: 'what do I have?' },
			{ role: 'assistant', content: null, tool_calls: [{ id: 'call_0' }] },
			{ role: 'tool', tool_call_id: 'call_0', content: '{}' },
			{ role: 'assistant', content: 'One spool.' },
			{ role: 'user', content: 'move it' },
			{ role: 'assistant', content: null, tool_calls: [{ id: 'call_0' }] }
		];
		expect(pairToolCalls(messages)).toEqual(messages.slice(0, 5));
	});

	it('drops a result that comes before its call', () => {
		const out = pairToolCalls([
			{ role: 'tool', tool_call_id: 'z', content: '{}' },
			{ role: 'user', content: 'q' },
			{ role: 'assistant', content: null, tool_calls: [{ id: 'z' }] }
		]);
		expect(out).toEqual([{ role: 'user', content: 'q' }]);
	});

	it('keeps the transcript the executed frame sends, without the system prompt', () => {
		const sent = [
			{ role: 'system', content: 'You are…' },
			{ role: 'user', content: 'move it' },
			{ role: 'assistant', content: null, tool_calls: [{ id: 'w1' }] },
			{ role: 'tool', tool_call_id: 'w1', content: '{"ok":true}' }
		];
		let s = startDecision(
			run(startTurn(initialChatState(), 'move it'), [
				[
					'confirm',
					{
						messages: sent.slice(0, 3),
						cards: [{ tool: 'update_spool', title: 'Move', summary: '', before: {}, after: {} }]
					}
				],
				['done', {}]
			])
		);
		s = run(s, [['executed', { cards: [{ tool: 'update_spool', summary: 'Moved.' }], messages: sent }]]);
		expect(s.messages).toEqual(sent.slice(1));
	});

	it('adds no bubble for an executed frame with no cards, but still takes its transcript', () => {
		const sent = [{ role: 'user', content: 'x' }];
		const s = run(startDecision(startTurn(initialChatState(), 'x')), [
			['executed', { cards: [], messages: sent }]
		]);
		expect(s.bubbles.map((b) => b.kind)).toEqual(['user']);
		expect(s.messages).toEqual(sent);
	});

	it('keeps an executed card when the drawer closes before the reply that follows it', () => {
		let s = startDecision(
			run(startTurn(initialChatState(), 'move it'), [
				[
					'confirm',
					{
						messages: [{ role: 'user', content: 'move it' }],
						cards: [{ tool: 't', title: 'T', summary: '', before: {}, after: {} }]
					}
				],
				['done', {}]
			])
		);
		s = run(s, [['executed', { cards: [{ tool: 't', summary: 'Moved.', undo: { tool: 'u' } }] }]]);
		expect(isDeciding(s)).toBe(true);
		const back = restoreChat(serialiseChat(s));
		expect(back?.bubbles.at(-1)).toEqual({
			kind: 'executed',
			cards: [{ tool: 't', summary: 'Moved.', undo: null }]
		});
	});

	it('stops counting as a decision once the turn ends', () => {
		const s = run(startDecision(startTurn(initialChatState(), 'x')), [['done', {}]]);
		expect(s.deciding).toBe(false);
	});
});

describe('a decision whose stream breaks off', () => {
	const deciding = () =>
		startDecision(
			run(startTurn(initialChatState(), 'move it'), [
				[
					'confirm',
					{
						messages: [{ role: 'user', content: 'move it' }],
						cards: [{ tool: 't', title: 'T', summary: '', before: {}, after: {} }]
					}
				],
				['done', {}]
			])
		);

	it('is marked as of unknown outcome when nothing came back', () => {
		const s = abandonTurn(deciding(), 'The assistant could not be reached.');
		expect(s.bubbles.slice(-2).map((b) => b.kind)).toEqual(['error', 'unknown']);
		expect(s.deciding).toBe(false);
	});

	it('is not marked unknown once the outcome arrived, and Stop works again', () => {
		const s = run(deciding(), [
			['executed', { cards: [{ tool: 't', summary: 'Moved.' }] }],
			['delta', { content: 'Done' }]
		]);
		expect(awaitingOutcome(s)).toBe(false);
		expect(abandonTurn(s).bubbles.at(-1)?.kind).toBe('executed');
		expect(stopTurn(s).status).toBe('idle');
	});
});

describe('a decision whose writes all failed', () => {
	it('counts the empty executed frame as its outcome', () => {
		let s = startDecision(
			run(startTurn(initialChatState(), 'move it'), [
				[
					'confirm',
					{
						messages: [{ role: 'user', content: 'move it' }],
						cards: [{ tool: 't', title: 'T', summary: '', before: {}, after: {} }]
					}
				],
				['done', {}]
			])
		);
		s = run(s, [
			['executed', { cards: [], messages: [{ role: 'user', content: 'move it' }] }],
			['delta', { content: 'It failed' }]
		]);
		expect(awaitingOutcome(s)).toBe(false);
		expect(stopTurn(s).status).toBe('idle');
		expect(abandonTurn(s).bubbles.map((b) => b.kind)).toEqual(['user', 'confirm']);
		// Nothing ran (failed writes are rolled back), so a reload shows it as not done.
		expect(restoreChat(serialiseChat(s))?.bubbles.at(-1)).toEqual({ kind: 'cancelled' });
	});
});
