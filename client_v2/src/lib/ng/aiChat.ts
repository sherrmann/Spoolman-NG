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
 *   - Nothing survives a reload, because nothing is stored anywhere else.
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

/** What the user sees, in order. */
export type Bubble =
	| { kind: 'user'; text: string }
	| { kind: 'assistant'; text: string }
	/** A read tool that ran on its own; shown so the answer is not unexplained. */
	| { kind: 'tool'; name: string; summary: string }
	| { kind: 'confirm'; cards: ConfirmCard[] }
	| { kind: 'executed'; cards: ExecutedCard[] }
	| { kind: 'cancelled' }
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
}

export function initialChatState(): ChatState {
	return { messages: [], bubbles: [], status: 'idle', pending: [] };
}

/** Add the user's turn and mark a stream as starting. */
export function startTurn(state: ChatState, text: string): ChatState {
	return {
		...state,
		messages: [...state.messages, { role: 'user', content: text }],
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
	return { ...state, status: 'streaming', pending: [] };
}

/** One decoded SSE frame from `POST /ai/chat`. */
export type ChatEvent =
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
			const d = frame.data as { name?: unknown; summary?: unknown };
			return {
				...state,
				// Not added to the transcript: the server already appended the tool result to the
				// convo it sends back. Adding our own would duplicate it.
				bubbles: [
					...state.bubbles,
					{ kind: 'tool', name: String(d.name ?? ''), summary: String(d.summary ?? '') }
				]
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
				messages: d.messages ?? state.messages,
				bubbles: [...state.bubbles, { kind: 'confirm', cards }],
				status: 'awaiting_confirm',
				pending: cards
			};
		}

		case 'executed': {
			const cards = (frame.data as { cards?: ExecutedCard[] }).cards ?? [];
			return { ...state, bubbles: [...state.bubbles, { kind: 'executed', cards }] };
		}

		case 'cancelled':
			return { ...state, bubbles: [...state.bubbles, { kind: 'cancelled' }] };

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
