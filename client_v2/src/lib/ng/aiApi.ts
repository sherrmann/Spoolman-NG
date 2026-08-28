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
import type { NlSearchResult } from './nlSearch';

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
	return flag('ai_feature_chat', signal);
}

/** One boolean AI setting, defaulting to off when it cannot be read. See chatFeatureEnabled. */
async function flag(key: string, signal?: AbortSignal): Promise<boolean> {
	try {
		return parseSetting((await getSettings(signal))[key], false);
	} catch {
		return false;
	}
}

/**
 * The three switches the chat surfaces read, fetched together.
 *
 * One request rather than three: they come from the same map, and the drawer needs all of them
 * before it can decide what to render.
 */
export async function chatSwitches(signal?: AbortSignal): Promise<{
	chat: boolean;
	voice: boolean;
	/** Send a transcript straight away instead of dropping it in the box to review. */
	voiceAutosend: boolean;
}> {
	try {
		const s = await getSettings(signal);
		return {
			chat: parseSetting(s.ai_feature_chat, false),
			voice: parseSetting(s.ai_feature_voice, false),
			voiceAutosend: parseSetting(s.ai_voice_autosend, false)
		};
	} catch {
		return { chat: false, voice: false, voiceAutosend: false };
	}
}

/** Whether natural-language search is switched on. */
export function nlSearchEnabled(signal?: AbortSignal): Promise<boolean> {
	return flag('ai_feature_nl_search', signal);
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

/**
 * Send a recorded clip for transcription.
 *
 * Multipart with the field named `file`, which is what the endpoint's signature requires. The
 * filename is a hint to the speech-to-text provider about the container -- the real content
 * type rides on the Blob -- so it is derived from what was actually recorded rather than
 * hardcoded to .webm, which would mislabel a Safari recording as something it is not.
 *
 * Not routed through $lib/api/http: that module sends JSON bodies, and setting a content-type
 * header on a FormData request is worse than leaving it off, since the boundary has to come
 * from the browser.
 */
export async function transcribe(clip: Blob, signal?: AbortSignal): Promise<string> {
	const form = new FormData();
	form.append('file', clip, filenameFor(clip.type));
	const res = await fetch(API_BASE + '/ai/transcribe', { method: 'POST', body: form, signal });
	if (!res.ok) throw new TranscribeError(transcribeFailure(res.status));
	const body = (await res.json()) as { text?: unknown };
	return String(body.text ?? '');
}

/** Why a clip could not be turned into text. Each maps to different advice. */
export type TranscribeFailure =
	/** 404 -- the voice feature is off server-side. */
	| 'disabled'
	/** 409 -- no speech-to-text endpoint configured. */
	| 'unconfigured'
	/** 413 -- the clip was too long. */
	| 'too_long'
	/** 400 -- nothing was captured, usually a press too short to record anything. */
	| 'empty'
	/** 502 and anything else. */
	| 'failed';

export class TranscribeError extends Error {
	constructor(readonly failure: TranscribeFailure) {
		super(`Transcription failed: ${failure}`);
		this.name = 'TranscribeError';
	}
}

function transcribeFailure(status: number): TranscribeFailure {
	if (status === 404) return 'disabled';
	if (status === 409) return 'unconfigured';
	if (status === 413) return 'too_long';
	if (status === 400) return 'empty';
	return 'failed';
}

/** A filename whose extension matches what was recorded, for the provider's container sniffing. */
function filenameFor(mimeType: string): string {
	if (mimeType.includes('mp4')) return 'clip.mp4';
	if (mimeType.includes('ogg')) return 'clip.ogg';
	return 'clip.webm';
}

/**
 * Translate a free-text search into filters.
 *
 * A single JSON reply, not a stream: the server does one completion and grounds every value
 * against the real vocabulary before answering, so there is nothing to show progressively.
 *
 * `translate()` never raises server-side -- a provider failure degrades to "the whole query is
 * free text" rather than an error -- so a rejection here means the feature is off (404), not
 * configured (409), or the request itself failed.
 */
export async function nlSearch(query: string, locale: string): Promise<NlSearchResult> {
	const res = await postJson<Record<string, unknown>>('/ai/nl-search', { query, locale });
	return {
		filters: Array.isArray(res.filters) ? (res.filters as NlSearchResult['filters']) : [],
		search: typeof res.search === 'string' ? res.search : null,
		color_hex: typeof res.color_hex === 'string' ? res.color_hex : null,
		sort: (res.sort as NlSearchResult['sort']) ?? null
	};
}

// --- operator settings -------------------------------------------------------------------
//
// Everything below is for the settings panel, and only an administrator can use any of it:
// /ai/config, /ai/probe and the Ollama endpoints all answer 403 otherwise, and /ai/status
// silently strips the provider fields rather than refusing. That stripping is why the panel
// asks who it is talking to first -- a read-only user shown an empty form cannot tell it from
// an unconfigured server, and finds out only when Save fails.

/** Whether this user may operate the assistant's configuration. */
export async function isAdmin(signal?: AbortSignal): Promise<boolean> {
	try {
		const me = await getJson<{ role?: unknown }>('/auth/me', {}, signal);
		return String(me.role ?? '') === 'admin';
	} catch {
		// Auth may be switched off entirely, in which case /auth/me still answers with the
		// implicit admin principal. A hard failure here is a broken or unreachable backend, and
		// the panel's own requests will report that far better than a hidden panel would.
		return true;
	}
}

/** Three-valued, because "we could not tell" is a real answer for a non-Ollama endpoint. */
export type TriState = 'yes' | 'no' | 'unknown';

export interface AiCapabilities {
	ok: boolean;
	error?: string;
	latencyMs?: number;
	models: string[];
	chat: TriState;
	tools: TriState;
	vision: TriState;
	isOllama: boolean;
}

/** The whole status an administrator sees, including what a non-admin never gets. */
export interface AiAdminStatus extends AiStatus {
	baseUrl: string;
	model: string;
	visionModel: string;
	apiKeySet: boolean;
	sttBaseUrl: string;
	sttModel: string;
	sttApiKeySet: boolean;
	/** Attribute names fixed by environment variables, which the form must not pretend to own. */
	envLocked: string[];
	features: Record<string, boolean>;
	/** The most recent probe the SERVER ran, if any. Not re-run by asking for status. */
	capabilities: AiCapabilities | null;
}

function mapCapabilities(raw: Record<string, unknown> | null | undefined): AiCapabilities | null {
	if (!raw) return null;
	const tri = (v: unknown): TriState => (v === 'yes' || v === 'no' ? v : 'unknown');
	return {
		ok: Boolean(raw.ok),
		error: raw.error == null ? undefined : String(raw.error),
		latencyMs: raw.latency_ms == null ? undefined : Number(raw.latency_ms),
		models: Array.isArray(raw.models) ? raw.models.map(String) : [],
		chat: tri(raw.chat),
		tools: tri(raw.tools),
		vision: tri(raw.vision),
		isOllama: Boolean(raw.is_ollama)
	};
}

export async function aiAdminStatus(signal?: AbortSignal): Promise<AiAdminStatus> {
	const r = await getJson<Record<string, unknown>>('/ai/status', {}, signal);
	const str = (v: unknown) => (v == null ? '' : String(v));
	return {
		configured: Boolean(r.configured),
		sttConfigured: Boolean(r.stt_configured),
		baseUrl: str(r.base_url),
		model: str(r.model),
		visionModel: str(r.vision_model),
		apiKeySet: Boolean(r.api_key_set),
		sttBaseUrl: str(r.stt_base_url),
		sttModel: str(r.stt_model),
		sttApiKeySet: Boolean(r.stt_api_key_set),
		envLocked: Array.isArray(r.env_locked) ? r.env_locked.map(String) : [],
		features: (r.features as Record<string, boolean> | undefined) ?? {},
		capabilities: mapCapabilities(r.capabilities as Record<string, unknown> | null)
	};
}

/**
 * Test an endpoint, optionally with values the operator has typed but not saved.
 *
 * Overrides exist so "Test connection" answers about the form in front of you rather than about
 * what is stored -- otherwise the only way to check a new URL is to save it first, which means
 * breaking a working setup to find out whether the replacement works.
 */
export async function aiProbe(overrides: {
	baseUrl?: string;
	apiKey?: string;
	model?: string;
	visionModel?: string;
}): Promise<AiCapabilities> {
	const body: Record<string, unknown> = {};
	if (overrides.baseUrl) body.base_url = overrides.baseUrl;
	if (overrides.apiKey) body.api_key = overrides.apiKey;
	if (overrides.model) body.model = overrides.model;
	if (overrides.visionModel) body.vision_model = overrides.visionModel;
	const raw = await postJson<Record<string, unknown>>('/ai/probe', body);
	return mapCapabilities(raw) as AiCapabilities;
}

/**
 * Store or clear an API key.
 *
 * `null` clears; a string replaces. Omitting a field entirely leaves that key alone, which is
 * what makes "save the form without retyping your key" work -- the server acts only on keys
 * actually present in the body.
 */
export async function setAiKeys(keys: { apiKey?: string | null; sttApiKey?: string | null }): Promise<void> {
	const body: Record<string, unknown> = {};
	if (keys.apiKey !== undefined) body.api_key = keys.apiKey;
	if (keys.sttApiKey !== undefined) body.stt_api_key = keys.sttApiKey;
	await postJson('/ai/config', body);
}

export interface OllamaModels {
	isOllama: boolean;
	installed: string[];
}

export async function ollamaModels(signal?: AbortSignal): Promise<OllamaModels> {
	try {
		const r = await getJson<Record<string, unknown>>('/ai/ollama/models', {}, signal);
		return {
			isOllama: Boolean(r.is_ollama),
			installed: Array.isArray(r.installed) ? r.installed.map(String) : []
		};
	} catch {
		return { isOllama: false, installed: [] };
	}
}

/** One frame of a model download. `percent` is absent until the server knows the total. */
export interface OllamaPullProgress {
	status: string;
	percent?: number;
}

/**
 * Pull a model, yielding progress as it arrives.
 *
 * Same SSE machinery as the chat, reusing the same parser: a model is gigabytes, and a download
 * with no visible progress is indistinguishable from one that has hung.
 */
export async function* pullOllamaModel(
	model: string,
	signal?: AbortSignal
): AsyncGenerator<OllamaPullProgress> {
	const res = await fetch(API_BASE + '/ai/ollama/pull', {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ model }),
		signal
	});
	if (!res.ok || !res.body) throw new Error(`Pull failed: ${res.status}`);

	const reader = res.body.getReader();
	const decoder = new TextDecoder();
	const parser = createSseParser();
	try {
		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
				let data: Record<string, unknown>;
				try {
					data = JSON.parse(frame.data) as Record<string, unknown>;
				} catch {
					continue;
				}
				if (frame.event === 'error') throw new Error(String(data.message ?? 'Pull failed'));
				if (frame.event === 'progress') {
					yield {
						status: String(data.status ?? ''),
						percent: data.percent == null ? undefined : Number(data.percent)
					};
				}
			}
		}
	} finally {
		reader.releaseLock();
	}
}
