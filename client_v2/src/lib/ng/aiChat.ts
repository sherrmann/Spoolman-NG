/**
 * The chat protocol's state, kept out of the component so a whole conversation -- including a
 * mutation the user confirms -- can be driven in a unit test without a model, a server or a
 * browser.
 *
 * The protocol is STATELESS on the server: `messages` is the entire transcript in OpenAI shape,
 * held here and re-posted every turn (spoolman/api/v1/ai.py, ChatRequest). Two consequences
 * shape this module:
 *
 *   - A `confirm` frame carries its own `messages`, and that transcript REPLACES ours. It is the
 *     convo including the assistant's pending tool calls, which the server needs back verbatim
 *     to resolve them. Re-posting our pre-confirm copy instead would ask the model to decide all
 *     over again, and the user's "yes" would apply to a mutation nobody previewed. This is the
 *     single most important line in the file.
 *   - The server keeps nothing, so a conversation that should survive a reload has to be kept
 *     here: serialiseChat/restoreChat below, which the drawer writes to localStorage.
 *
 * The bubbles are separate from the transcript on purpose. The transcript is what the model
 * needs; the bubbles are what the user reads, and they include things the model never said --
 * which tools ran, what a mutation would change, what was executed.
 */

/** One OpenAI-shaped transcript entry. Opaque here: it is round-tripped, never interpreted. */
export type ChatMessage = Record<string, unknown>;

/** A mutation previewed but not yet run (spoolman/ai_tools/base.py, ConfirmCard). */
export interface ConfirmCard {
	tool_call_id?: string;
	tool: string;
	title: string;
	summary: string;
	before: Record<string, unknown>;
	after: Record<string, unknown>;
	destructive?: boolean;
}

/** A mutation that ran, with the descriptor that would undo it. */
export interface ExecutedCard {
	tool: string;
	summary: string;
	undo?: { tool: string; args?: Record<string, unknown> } | null;
}

/** One result row of a read tool, as the server whitelisted it. Field set varies by tool. */
export type ToolRow = Record<string, unknown>;

/** One bucket of `get_usage_stats`. */
export interface UsagePeriod {
	period: string;
	consumed_weight: number;
	cost: number;
}

/** What the user sees, in order. */
export type Bubble =
	| { kind: 'user'; text: string }
	| { kind: 'assistant'; text: string }
	/**
	 * A read tool that ran on its own; shown so the answer is not unexplained. `rows`, `total`
	 * and `periods` come straight from the tool's own result (spoolman/aichat.py, _card_payload),
	 * so a card can only show what the tool returned.
	 */
	| {
			kind: 'tool';
			name: string;
			summary: string;
			rows?: ToolRow[];
			total?: number;
			periods?: UsagePeriod[];
			filters?: Record<string, unknown>;
	  }
	| { kind: 'confirm'; cards: ConfirmCard[] }
	| { kind: 'executed'; cards: ExecutedCard[] }
	| { kind: 'cancelled' }
	/**
	 * A confirmation whose answer was sent but whose outcome never arrived (the drawer was closed
	 * or the page reloaded mid-decision). The write may or may not have run.
	 */
	| { kind: 'unknown' }
	| { kind: 'error'; text: string };

export type ChatStatus =
	/** Nothing in flight. */
	| 'idle'
	/** A turn is streaming. */
	| 'streaming'
	/** The stream stopped on a preview and will not resume until the user decides. */
	| 'awaiting_confirm';

export interface ChatState {
	/** The transcript, exactly as the server will get it back. */
	messages: ChatMessage[];
	bubbles: Bubble[];
	status: ChatStatus;
	/** The cards awaiting a decision; empty unless `status` is 'awaiting_confirm'. */
	pending: ConfirmCard[];
	/**
	 * Reply text streamed so far by `delta` frames. Display only: it never enters the
	 * transcript, and the next frame of any other kind clears it, because the server's
	 * `message` frame carries the final answer in full and text written before a tool call is
	 * not an answer at all.
	 */
	streaming: string;
	/**
	 * Whether the turn in flight answers a confirmation (confirm or cancel) rather than asking
	 * something new. The server runs confirmed writes before it sends anything back, so such a
	 * turn must not be stopped or cleared, and closing the drawer mid-way must not later read
	 * as a cancellation.
	 */
	deciding: boolean;
}

export function initialChatState(): ChatState {
	return { messages: [], bubbles: [], status: 'idle', pending: [], streaming: '', deciding: false };
}

/** Add the user's turn and mark a stream as starting. */
export function startTurn(state: ChatState, text: string): ChatState {
	return {
		...state,
		// A new question never resolves anything pending, so every tool call must already have
		// its result. One may not after a decision whose outcome never arrived, or in a restored
		// or trimmed transcript; strict endpoints refuse such a history (HTTP 400).
		messages: [...pairToolCalls(state.messages), { role: 'user', content: text }],
		bubbles: [...state.bubbles, { kind: 'user', text }],
		status: 'streaming',
		pending: []
	};
}

/**
 * Begin resolving a pending mutation.
 *
 * The transcript is left exactly as the `confirm` frame set it -- the decision travels in the
 * request's `decision` field, not as another message.
 */
export function startDecision(state: ChatState): ChatState {
	return { ...state, status: 'streaming', pending: [], deciding: true };
}

/**
 * End a turn the user stopped.
 *
 * Text already streamed stays, as a reply in both the bubbles and the transcript: the user has
 * read it, and the model should know it said it. Nothing else of the turn reached this client
 * (the server returns its tool results only with a confirmation), so there is nothing more
 * to keep. A turn waiting on a confirmation is not a turn in flight and is left alone.
 */
export function stopTurn(state: ChatState): ChatState {
	// A decision whose outcome has not arrived cannot be stopped: the server runs the confirmed
	// writes before it sends anything back, so stopping would only hide what happened.
	if (state.status !== 'streaming' || awaitingOutcome(state)) return state;
	const text = state.streaming.trim();
	if (!text) return { ...state, status: 'idle', streaming: '', deciding: false };
	return {
		...state,
		messages: [...state.messages, { role: 'assistant', content: text }],
		bubbles: [...state.bubbles, { kind: 'assistant', text }],
		status: 'idle',
		streaming: '',
		deciding: false
	};
}

/** Whether the turn in flight is a confirm/cancel answer rather than a new question. */
export function isDeciding(state: ChatState): boolean {
	return state.status === 'streaming' && state.deciding;
}

/**
 * Whether a decision is in flight and its outcome (`executed` or `cancelled`) has not arrived:
 * the only time the confirmed writes may or may not have run. Once the outcome is shown, the
 * rest of the turn is an ordinary reply.
 */
export function awaitingOutcome(state: ChatState): boolean {
	return isDeciding(state) && state.bubbles[state.bubbles.length - 1]?.kind === 'confirm';
}

/** End a turn whose stream broke off; a decision without its outcome is marked as unknown. */
export function abandonTurn(state: ChatState, error?: string): ChatState {
	const bubbles: Bubble[] = [...state.bubbles];
	if (error) bubbles.push({ kind: 'error', text: error });
	if (awaitingOutcome(state)) bubbles.push({ kind: 'unknown' });
	return { ...state, status: 'idle', deciding: false, streaming: '', bubbles };
}

/**
 * The transcript with every tool call paired to its result.
 *
 * Drops an assistant turn whose tool calls do not all have a `tool` result after it (keeping
 * its text, if it had any, as a plain reply), and any `tool` result whose call is gone.
 * Providers reject either half on its own.
 */
export function pairToolCalls(messages: ChatMessage[]): ChatMessage[] {
	const kept: ChatMessage[] = [];
	for (let i = 0; i < messages.length; i++) {
		const m = messages[i];
		const toolCalls = m.role === 'assistant' && Array.isArray(m.tool_calls) ? m.tool_calls : [];
		if (toolCalls.length === 0) {
			// A result not directly after its call turn has nothing to answer.
			if (m.role !== 'tool') kept.push(m);
			continue;
		}
		// Pair by position, not by id across the whole transcript: providers that send no ids
		// get ones numbered per response, so `call_0` can recur in every round.
		let j = i + 1;
		const results: ChatMessage[] = [];
		while (j < messages.length && messages[j].role === 'tool') results.push(messages[j++]);
		const ids = toolCalls.map((c) => (c as { id?: unknown } | null)?.id);
		const answered = new Set(results.map((r) => r.tool_call_id));
		const complete =
			ids.every((id) => typeof id === 'string' && answered.has(id)) && new Set(ids).size === ids.length;
		if (complete) {
			kept.push(m);
			const seen = new Set<unknown>();
			for (const r of results) {
				if (ids.includes(r.tool_call_id) && !seen.has(r.tool_call_id)) {
					seen.add(r.tool_call_id);
					kept.push(r);
				}
			}
		} else if (typeof m.content === 'string' && m.content.trim()) {
			kept.push({ role: 'assistant', content: m.content });
		}
		i = j - 1;
	}
	return kept;
}

/** One decoded SSE frame from `POST /ai/chat`. */
export type ChatEvent =
	| { event: 'delta'; data: { content?: string } }
	| { event: 'message'; data: { content?: string } }
	| { event: 'tool'; data: { name?: string; summary?: string } }
	| { event: 'confirm'; data: { messages?: ChatMessage[]; cards?: ConfirmCard[] } }
	| { event: 'executed'; data: { cards?: ExecutedCard[] } }
	| { event: 'cancelled'; data: Record<string, never> }
	| { event: 'error'; data: { message?: string } }
	| { event: 'done'; data: Record<string, never> }
	| { event: string; data: Record<string, unknown> };

/**
 * Fold one frame into the state.
 *
 * Pure and total: an unrecognised event is ignored rather than thrown on, so a server that
 * grows a new frame type does not break a client that has not learned it yet.
 */
export function applyChatEvent(state: ChatState, frame: ChatEvent): ChatState {
	if (frame.event === 'delta') {
		const piece = (frame.data as { content?: unknown }).content;
		if (typeof piece !== 'string' || !piece || state.status !== 'streaming') return state;
		return { ...state, streaming: state.streaming + piece };
	}
	// Every other frame supersedes whatever was streamed before it.
	let next = foldFrame(state, frame);
	if (next.streaming) next = { ...next, streaming: '' };
	if (next.deciding && next.status !== 'streaming') next = { ...next, deciding: false };
	return next;
}

function foldFrame(state: ChatState, frame: ChatEvent): ChatState {
	switch (frame.event) {
		case 'message': {
			const text = String((frame.data as { content?: unknown }).content ?? '');
			if (!text) return state;
			return {
				...state,
				// The assistant's own words go into the transcript too: the next turn has to see
				// what it already said, or it repeats itself.
				messages: [...state.messages, { role: 'assistant', content: text }],
				bubbles: [...state.bubbles, { kind: 'assistant', text }]
			};
		}

		case 'tool': {
			const d = frame.data as Record<string, unknown>;
			const bubble: Bubble = { kind: 'tool', name: String(d.name ?? ''), summary: String(d.summary ?? '') };
			if (Array.isArray(d.rows)) {
				bubble.rows = d.rows.filter((r): r is ToolRow => typeof r === 'object' && r !== null);
				if (typeof d.total === 'number') bubble.total = d.total;
			}
			if (Array.isArray(d.periods)) bubble.periods = d.periods.filter(isUsagePeriod);
			if (d.filters && typeof d.filters === 'object') bubble.filters = d.filters as Record<string, unknown>;
			return {
				...state,
				// Not added to the transcript: the server already appended the tool result to the
				// convo it sends back. Adding our own would duplicate it.
				bubbles: [...state.bubbles, bubble]
			};
		}

		case 'confirm': {
			const d = frame.data as { messages?: ChatMessage[]; cards?: ConfirmCard[] };
			const cards = d.cards ?? [];
			return {
				...state,
				// REPLACED, not appended. See this module's opening comment: this transcript
				// carries the assistant's pending tool calls, and the server needs it back
				// verbatim to know what the user is saying yes to.
				messages: transcriptFrom(d.messages) ?? state.messages,
				bubbles: [...state.bubbles, { kind: 'confirm', cards }],
				status: 'awaiting_confirm',
				pending: cards
			};
		}

		case 'executed': {
			const d = frame.data as { cards?: ExecutedCard[]; messages?: unknown };
			const cards = d.cards ?? [];
			return {
				...state,
				// The server sends the transcript with the writes' results; keep it, so the next
				// turn tells the model what actually ran.
				messages: transcriptFrom(d.messages) ?? state.messages,
				// No cards means every confirmed write failed; the transcript still matters.
				bubbles: cards.length ? [...state.bubbles, { kind: 'executed', cards }] : state.bubbles
			};
		}

		case 'cancelled':
			return {
				...state,
				messages: transcriptFrom((frame.data as { messages?: unknown }).messages) ?? state.messages,
				bubbles: [...state.bubbles, { kind: 'cancelled' }]
			};

		case 'error': {
			const text = String((frame.data as { message?: unknown }).message ?? '');
			return { ...state, bubbles: [...state.bubbles, { kind: 'error', text }] };
		}

		case 'done':
			// A turn that stopped on a preview stays awaiting a decision -- `done` closes the
			// HTTP stream, it does not mean the exchange finished.
			return state.status === 'awaiting_confirm' ? state : { ...state, status: 'idle' };

		default:
			return state;
	}
}

/**
 * Decode a frame's JSON payload, or null if it is not usable.
 *
 * Malformed JSON is dropped rather than thrown on: one bad frame mid-stream should cost that
 * frame, not the conversation the user has been having.
 */
export function decodeChatFrame(event: string, data: string): ChatEvent | null {
	try {
		const parsed: unknown = JSON.parse(data);
		if (typeof parsed !== 'object' || parsed === null) return null;
		return { event, data: parsed as Record<string, unknown> } as ChatEvent;
	} catch {
		return null;
	}
}

/**
 * A transcript sent by the server, without its system prompt (the server always replaces it,
 * so keeping it would only take up the stored conversation), or null if it is not one.
 */
function transcriptFrom(value: unknown): ChatMessage[] | null {
	if (!Array.isArray(value)) return null;
	return value.filter(
		(m): m is ChatMessage => typeof m === 'object' && m !== null && (m as ChatMessage).role !== 'system'
	);
}

function isUsagePeriod(value: unknown): value is UsagePeriod {
	if (typeof value !== 'object' || value === null) return false;
	const p = value as Record<string, unknown>;
	return typeof p.period === 'string' && typeof p.consumed_weight === 'number';
}

// --- Keeping a conversation across reloads ------------------------------------------------

/** localStorage key. The version is part of the key so an old shape is simply not found. */
export const CHAT_STORAGE_KEY = 'spoolman.chat.v1';

/**
 * As many transcript entries as the server reads (spoolman/aichat.py, _MAX_CLIENT_MESSAGES);
 * anything older would be cut there anyway.
 */
const MAX_STORED_MESSAGES = 40;
const MAX_STORED_BUBBLES = 80;
/** A stored chat bigger than this is trimmed from the oldest end until it fits. */
const MAX_STORED_CHARS = 200_000;

/**
 * The conversation as a string to store, or null when there is nothing worth keeping.
 *
 * Only a settled conversation is kept. A turn still streaming is not stored, and neither is a
 * pending confirmation: the server would run the previewed writes on "confirm" whatever has
 * changed since, so a card restored tomorrow could apply yesterday's numbers. restoreChat
 * turns such a card into a cancellation instead.
 */
export function serialiseChat(state: ChatState): string | null {
	// A decision in flight is stored, marked as sent, so that a close or reload before its
	// outcome arrives is not later shown as a cancellation it may not have been.
	const decisionSent = isDeciding(state);
	if ((state.status === 'streaming' && !decisionSent) || state.bubbles.length === 0) return null;
	let messages = trimToUserTurn(state.messages.slice(-MAX_STORED_MESSAGES));
	let bubbles = state.bubbles.slice(-MAX_STORED_BUBBLES);
	const pack = () =>
		JSON.stringify(decisionSent ? { messages, bubbles, decisionSent } : { messages, bubbles });
	let raw = pack();
	while (raw.length > MAX_STORED_CHARS && (messages.length > 1 || bubbles.length > 1)) {
		messages = trimToUserTurn(messages.slice(Math.ceil(messages.length / 4)));
		bubbles = bubbles.slice(Math.ceil(bubbles.length / 4));
		raw = pack();
	}
	return raw.length > MAX_STORED_CHARS ? null : raw;
}

/**
 * The conversation a stored string describes, or null if it is missing or unusable.
 *
 * A conversation stored while a confirmation was pending comes back with that confirmation
 * cancelled (or, if the answer had already been sent, marked as of unknown outcome) and every
 * unanswered tool call removed from the transcript, so nothing can be confirmed from a stale
 * card and the next turn sends the model a valid history. Undo buttons do not come back.
 */
export function restoreChat(raw: string | null): ChatState | null {
	if (!raw) return null;
	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch {
		return null;
	}
	if (typeof parsed !== 'object' || parsed === null) return null;
	const { messages, bubbles, decisionSent } = parsed as {
		messages?: unknown;
		bubbles?: unknown;
		decisionSent?: unknown;
	};
	if (!Array.isArray(messages) || !Array.isArray(bubbles)) return null;
	const cleanMessages = messages.filter((m): m is ChatMessage => typeof m === 'object' && m !== null);
	const cleanBubbles = bubbles.filter(
		(b): b is Bubble =>
			typeof b === 'object' && b !== null && typeof (b as { kind?: unknown }).kind === 'string'
	);
	if (cleanBubbles.length === 0) return null;

	if (cleanBubbles[cleanBubbles.length - 1].kind === 'confirm') {
		cleanBubbles[cleanBubbles.length - 1] =
			decisionSent === true ? { kind: 'unknown' } : { kind: 'cancelled' };
	}
	// An undo descriptor restores the values from before its write, so it is only safe straight
	// after that write; replayed days later it would throw away everything recorded since.
	const settled = cleanBubbles.map((b) =>
		b.kind === 'executed' ? { ...b, cards: (b.cards ?? []).map((c) => ({ ...c, undo: null })) } : b
	);
	return { ...initialChatState(), messages: pairToolCalls(cleanMessages), bubbles: settled };
}

/**
 * Drop leading entries until the transcript starts at a user turn.
 *
 * Cutting a transcript at an arbitrary point can leave a tool result whose call was cut off,
 * which providers reject. Starting at a user turn never splits a call from its result.
 */
function trimToUserTurn(messages: ChatMessage[]): ChatMessage[] {
	const first = messages.findIndex((m) => m.role === 'user');
	if (first === -1) return [];
	return first === 0 ? messages : messages.slice(first);
}

/** Read the stored conversation. Storage may be unavailable (private mode); that is no chat. */
export function loadStoredChat(): ChatState | null {
	try {
		return restoreChat(globalThis.localStorage?.getItem(CHAT_STORAGE_KEY) ?? null);
	} catch {
		return null;
	}
}

/** Store the conversation, or remove the stored one when there is nothing worth keeping. */
export function saveStoredChat(state: ChatState): void {
	try {
		const raw = serialiseChat(state);
		if (raw !== null) globalThis.localStorage?.setItem(CHAT_STORAGE_KEY, raw);
		else if (state.bubbles.length === 0) globalThis.localStorage?.removeItem(CHAT_STORAGE_KEY);
	} catch {
		/* storage full or unavailable: the conversation still works for this page */
	}
}

/** Forget the stored conversation (Clear chat, and logging out). */
export function clearStoredChat(): void {
	try {
		globalThis.localStorage?.removeItem(CHAT_STORAGE_KEY);
	} catch {
		/* nothing stored to clear */
	}
}
