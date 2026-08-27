/**
 * The assistant's endpoints. Separate from ./api.ts, which is about this fork's entities: this
 * one talks to a model and has an entirely different failure vocabulary.
 *
 * `POST /ai/chat` cannot go through $lib/api/http like everything else, because that module
 * reads whole JSON bodies and this response is a Server-Sent Events stream that has to be
 * consumed as it arrives. `EventSource` is not an option either -- it only issues GET and
 * carries no body, and the chat protocol posts the entire transcript every turn. So this one
 * call is a raw `fetch` against the same API_BASE, with the status handling written out rather
 * than inherited.
 */
import { API_BASE } from '$lib/api/config';
import { getJson, postJson } from '$lib/api/http';
import { getSettings, parseSetting } from '$lib/api/settings';
import { createSseParser } from './sse';
import { decodeChatFrame, type ChatEvent, type ChatMessage } from './aiChat';

/**
 * Whether the assistant is switched on at all.
 *
 * Read from the generic settings endpoint rather than /ai/status, matching the React client:
 * `ai_feature_chat` is an ordinary registered boolean, defaulting to false, and everything AI
 * is invisible until an operator turns it on. Read here rather than added to $lib/stores/
 * settings, which hardcodes the three keys upstream cares about -- one extra request when the
 * drawer first mounts is cheaper than an edit to a vendored store.
 *
 * Any failure reads as "off". A settings endpoint that cannot be reached is not a reason to
 * show a chat button that will 404 the moment it is pressed.
 */
export async function chatFeatureEnabled(signal?: AbortSignal): Promise<boolean> {
	try {
		return parseSetting((await getSettings(signal)).ai_feature_chat, false);
	} catch {
		return false;
	}
}

export interface AiStatus {
	/** An endpoint and a model are both configured. Without this, /ai/chat answers 409. */
	configured: boolean;
	/** Speech-to-text is configured. Reported for the voice feature, which is not ported yet. */
	sttConfigured: boolean;
}

/**
 * The readiness a non-admin is allowed to see.
 *
 * The endpoint returns far more to an administrator -- endpoint URLs, model names, probe
 * results -- and strips all of it for everyone else (spoolman/api/v1/ai.py:143-150). Only the
 * two booleans every caller gets are mapped here, because the operator detail belongs to the
 * settings page and this client has no AI settings page.
 */
export async function aiStatus(signal?: AbortSignal): Promise<AiStatus> {
	try {
		const res = await getJson<Record<string, unknown>>('/ai/status', {}, signal);
		return { configured: Boolean(res.configured), sttConfigured: Boolean(res.stt_configured) };
	} catch {
		return { configured: false, sttConfigured: false };
	}
}

/** Why a turn could not start. Each is a distinct HTTP status, and each needs different wording. */
export type ChatStartFailure =
	/** 404 -- the feature is off server-side, whatever the client's settings said. */
	| 'disabled'
	/** 409 -- no endpoint and model configured yet. An operator has to finish setting it up. */
	| 'unconfigured'
	/** 503 -- too many turns already in flight. Worth retrying in a moment. */
	| 'busy'
	/** Anything else, including a dropped connection. */
	| 'failed';

export class ChatStartError extends Error {
	constructor(readonly failure: ChatStartFailure) {
		super(`Chat could not start: ${failure}`);
		this.name = 'ChatStartError';
	}
}

export interface ChatTurnBody {
	messages: ChatMessage[];
	/** What the user is looking at, so the assistant can resolve "this spool". Server caps it. */
	context?: string;
	locale?: string;
	/** Resolves the writes a previous `confirm` frame left pending. */
	decision?: 'confirm' | 'cancel';
}

/**
 * Stream one turn, yielding each decoded frame as it arrives.
 *
 * Frames are yielded rather than collected because a turn can run several tools before it
 * answers, and the point of the stream is that the user sees that happening instead of watching
 * a spinner. A frame whose JSON will not parse is skipped: one bad frame should cost that
 * frame, not the conversation.
 *
 * The generator returns when the server closes the stream. Aborting `signal` ends it too --
 * and must be done when the drawer closes, or the turn keeps running against a screen nobody
 * is looking at.
 */
export async function* streamChat(body: ChatTurnBody, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
	const res = await fetch(API_BASE + '/ai/chat', {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({
			messages: body.messages,
			context: body.context,
			locale: body.locale ?? 'en',
			decision: body.decision
		}),
		signal
	});

	if (!res.ok) {
		// These three are answered before the stream opens, so they arrive as ordinary statuses
		// rather than as an `error` frame, and the UI has to tell them apart: "switch it on",
		// "finish configuring it" and "try again shortly" are three different instructions.
		if (res.status === 404) throw new ChatStartError('disabled');
		if (res.status === 409) throw new ChatStartError('unconfigured');
		if (res.status === 503) throw new ChatStartError('busy');
		throw new ChatStartError('failed');
	}
	if (!res.body) throw new ChatStartError('failed');

	const reader = res.body.getReader();
	const decoder = new TextDecoder();
	const parser = createSseParser();
	try {
		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			// `stream: true` keeps a multi-byte character split across two network chunks from
			// being decoded as two replacement characters.
			for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
				const decoded = decodeChatFrame(frame.event, frame.data);
				if (decoded !== null) yield decoded;
			}
		}
	} finally {
		// Releasing the lock lets the body be discarded promptly when a caller stops early,
		// which is what happens every time the user closes the drawer mid-turn.
		reader.releaseLock();
	}
}

export interface ChatActionResult {
	summary: string;
	undo?: Record<string, unknown> | null;
}

/**
 * Replay an undo descriptor the server itself issued.
 *
 * Deliberately NOT a general "run this tool" call, even though the request shape would allow
 * it: the only thing that should ever reach here is a `{tool, args}` taken verbatim from an
 * executed card's own `undo`. The server enforces that with an allowlist, hardened after a
 * create's undo descriptor named a delete whose cascade ran with no preview at all -- so the
 * UI should not present this as a generic action runner either.
 */
export async function chatUndo(tool: string, args: Record<string, unknown>): Promise<ChatActionResult> {
	const res = await postJson<Record<string, unknown>>('/ai/chat/action', { tool, args });
	return {
		summary: String(res.summary ?? ''),
		undo: (res.undo as Record<string, unknown> | null) ?? null
	};
}
