<script lang="ts">
	/**
	 * The assistant, as a right-hand drawer (#AI) -- ported from the React client's chatDrawer.
	 *
	 * The protocol and its chat live in $lib/ng/{aiChat,aiApi,sse}, tested without a model or a
	 * server; this file is the screen. What it has to get right on its own:
	 *
	 *  - The transcript is never persisted. It is client-held and re-posted whole each turn, so
	 *    a reload loses the conversation. That is upstream-of-us behaviour, not a shortcut here.
	 *  - A turn that stops on a preview is NOT finished. The composer stays shut and the cards
	 *    wait, because the server is holding writes that only a decision releases.
	 *  - Closing aborts the turn in flight. A stream left running writes into a chat nobody is
	 *    looking at, and on confirm it would be holding a mutation open.
	 *
	 * Voice -- push-to-talk and spoken replies -- is a separate feature flag in the React client
	 * and is deliberately not ported here; its keys come along with the message prefix but
	 * nothing renders them.
	 */
	import Button from '$components/Button.svelte';
	import X from '@lucide/svelte/icons/x';
	import Send from '@lucide/svelte/icons/send';
	import Mic from '@lucide/svelte/icons/mic';
	import Volume2 from '@lucide/svelte/icons/volume-2';
	import Wrench from '@lucide/svelte/icons/wrench';
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { getLocale } from '$lib/paraglide/runtime';
	import {
		streamChat,
		chatUndo,
		transcribe,
		chatSwitches,
		aiStatus,
		ChatStartError,
		TranscribeError,
		type ChatStartFailure,
		type TranscribeFailure,
		type ChatTurnBody
	} from '$lib/ng/aiApi';
	import { startRecording, voiceSupported, VoiceError, MAX_CLIP_MS, type Recording } from '$lib/ng/voice';
	import {
		applyChatEvent,
		initialChatState,
		startDecision,
		startTurn,
		type ChatState,
		type ExecutedCard
	} from '$lib/ng/aiChat';
	import { cardRows } from '$lib/ng/aiCards';

	interface Props {
		onclose: () => void;
	}
	let { onclose }: Props = $props();

	// Named `chat`, not `state`: Svelte reads `$state` in the initializer of a variable
	// called `state` as a store subscription to that same variable, and the compile fails
	// on a use-before-declaration that has nothing to do with the code.
	let chat = $state<ChatState>(initialChatState());
	let draft = $state('');
	let inFlight: AbortController | null = null;
	let list = $state<HTMLDivElement | null>(null);
	let input = $state<HTMLInputElement | null>(null);
	/** Undo descriptors already replayed, so a second press cannot run the same one twice. */
	let undone = $state(new Set<string>());

	// --- voice ------------------------------------------------------------------
	// Two independent halves. Dictation needs a speech-to-text endpoint on the server; speaking
	// replies is a browser API and needs nothing but the browser, which is why the toggle can be
	// available when the microphone is not.
	let voiceOn = $state(false);
	let autosend = $state(false);
	/**
	 * Whether the server has a transcription endpoint.
	 *
	 * Gating the microphone on the voice FLAG alone is not enough, and this is exactly the
	 * "dead button" case $lib/utils/nfc warns about: /ai/transcribe answers 409 with no
	 * speech-to-text configured, so the button would fail on every press with nothing on screen
	 * explaining why. Speaking replies is unaffected -- that is a browser API and needs no
	 * server at all, which is why the two are gated separately rather than together.
	 */
	let sttReady = $state(false);
	let recording = $state(false);
	let transcribing = $state(false);
	let speak = $state(false);
	const canRecord = voiceSupported();
	const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window;
	/** The live recorder. Not $state: nothing renders from it, and it is pure bookkeeping. */
	let recorder: Recording | null = null;
	let clipTimer: ReturnType<typeof setTimeout> | null = null;

	let dialog = $state<HTMLDivElement | null>(null);
	let opener: HTMLElement | null = null;
	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		dialog?.focus();
		input?.focus();
		const controller = new AbortController();
		chatSwitches(controller.signal).then((s) => {
			voiceOn = s.voice;
			autosend = s.voiceAutosend;
			// Only asked when voice is on: a server with the feature off has nothing to say here.
			if (s.voice) aiStatus(controller.signal).then((st) => (sttReady = st.sttConfigured));
		});
		return () => {
			controller.abort();
			inFlight?.abort();
			// Everything the drawer started has to stop with it: a live microphone keeps the
			// browser's recording indicator on, and an utterance carries on talking to an empty
			// room.
			recorder?.cancel();
			recorder = null;
			if (clipTimer) clearTimeout(clipTimer);
			if (canSpeak) window.speechSynthesis.cancel();
			opener?.focus();
		};
	});

	// Follow the conversation as it grows. Reading `chat.bubbles.length` is what subscribes
	// this to new turns; the scroll itself is not reactive.
	$effect(() => {
		// Reading the count is what subscribes this effect to new turns; it also answers whether
		// there is anything to scroll to, so it is used rather than discarded.
		const count = chat.bubbles.length;
		if (list && count > 0) list.scrollTop = list.scrollHeight;
	});

	function close() {
		inFlight?.abort();
		onclose();
	}

	/** Turn a pre-stream HTTP status into something a user can act on. */
	function startFailureText(failure: ChatStartFailure): string {
		switch (failure) {
			case 'disabled':
				return ng.chat_error_disabled();
			case 'unconfigured':
				return ng.chat_error_unconfigured();
			case 'busy':
				return ng.chat_error_busy();
			default:
				return ng.chat_error_failed();
		}
	}

	async function drive(body: ChatTurnBody) {
		inFlight?.abort();
		const controller = new AbortController();
		inFlight = controller;
		try {
			for await (const frame of streamChat(body, controller.signal)) {
				chat = applyChatEvent(chat, frame);
				// Only the assistant's own words are spoken. Tool lines and card summaries are
				// scaffolding around the answer, and reading them aloud buries it.
				if (frame.event === 'message') {
					speakText(String((frame.data as { content?: unknown }).content ?? ''));
				}
			}
			// The server always ends a turn with `done`; if the connection dropped before one
			// arrived, the composer would stay disabled forever without this.
			if (chat.status === 'streaming') chat = { ...chat, status: 'idle' };
		} catch (e) {
			if (controller.signal.aborted) return; // our own close, not a failure
			const text = e instanceof ChatStartError ? startFailureText(e.failure) : ng.chat_error_failed();
			chat = {
				...chat,
				status: 'idle',
				bubbles: [...chat.bubbles, { kind: 'error', text }]
			};
		} finally {
			if (inFlight === controller) inFlight = null;
		}
	}

	async function send() {
		const text = draft.trim();
		if (!text || chat.status !== 'idle') return;
		draft = '';
		chat = startTurn(chat, text);
		await drive({ messages: chat.messages, locale: getLocale() });
	}

	async function decide(decision: 'confirm' | 'cancel') {
		if (chat.status !== 'awaiting_confirm') return;
		chat = startDecision(chat);
		// `chat.messages` here is the transcript the confirm frame carried, which the server
		// needs back verbatim -- see aiChat's opening comment.
		await drive({ messages: chat.messages, locale: getLocale(), decision });
	}

	function speakText(text: string) {
		if (!speak || !canSpeak || !text) return;
		// Cancel first: without it a second reply queues behind the first and the user hears an
		// answer to a question they have moved on from.
		window.speechSynthesis.cancel();
		window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
	}

	function toggleSpeak() {
		speak = !speak;
		if (!speak && canSpeak) window.speechSynthesis.cancel();
	}

	/** Turn a failed capture into something the user can act on. */
	function voiceErrorText(e: unknown): string {
		if (e instanceof TranscribeError) return transcribeFailureText(e.failure);
		if (e instanceof VoiceError) {
			return e.reason === 'notAllowed' || e.reason === 'unavailable'
				? ng.chat_voice_mic_error()
				: ng.chat_voice_unsupported();
		}
		return ng.chat_voice_mic_error();
	}

	function transcribeFailureText(failure: TranscribeFailure): string {
		switch (failure) {
			case 'disabled':
				return ng.chat_error_disabled();
			case 'unconfigured':
				return ng.chat_error_unconfigured();
			default:
				// too_long, empty and provider failures all mean "that clip did not become text",
				// and the user's next move is the same in each case: say it again.
				return ng.chat_voice_mic_error();
		}
	}

	async function startTalking() {
		if (recording || transcribing || chat.status !== 'idle') return;
		recording = true;
		try {
			recorder = await startRecording();
			// A held button can outlive the server's size limit. Stopping first turns "your clip
			// was refused" into a clip that simply ends.
			clipTimer = setTimeout(() => void stopTalking(false), MAX_CLIP_MS);
		} catch (e) {
			recording = false;
			recorder = null;
			chat = { ...chat, bubbles: [...chat.bubbles, { kind: 'error', text: voiceErrorText(e) }] };
		}
	}

	/**
	 * Release the button.
	 *
	 * `cancelled` is true when the pointer left the button rather than lifting off it, which is
	 * how a user abandons a recording they have thought better of -- the clip is discarded
	 * without being sent anywhere.
	 */
	async function stopTalking(cancelled: boolean) {
		if (clipTimer) {
			clearTimeout(clipTimer);
			clipTimer = null;
		}
		const active = recorder;
		recorder = null;
		recording = false;
		if (!active) return;
		if (cancelled) {
			active.cancel();
			return;
		}

		const clip = await active.stop();
		// A press too short to capture anything is not a failure worth reporting; the user
		// almost certainly meant to click something else.
		if (clip.size === 0) return;

		transcribing = true;
		try {
			const text = (await transcribe(clip)).trim();
			if (!text) return;
			if (autosend) {
				draft = text;
				await send();
			} else {
				// The default. Speech-to-text mangles vendor names, so the transcript lands in the
				// box for the user to fix before it is sent.
				draft = draft ? `${draft} ${text}` : text;
				input?.focus();
			}
		} catch (e) {
			chat = { ...chat, bubbles: [...chat.bubbles, { kind: 'error', text: voiceErrorText(e) }] };
		} finally {
			transcribing = false;
		}
	}

	async function undo(card: ExecutedCard, key: string) {
		if (!card.undo?.tool || undone.has(key)) return;
		try {
			await chatUndo(card.undo.tool, card.undo.args ?? {});
			undone = new Set([...undone, key]);
			toasts.success(ng.chat_executed_undone());
		} catch {
			toasts.error(ng.chat_error_failed());
		}
	}
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && close()} />

<div class="overlay">
	<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={close}></button>
	<div
		class="drawer"
		role="dialog"
		aria-modal="true"
		aria-label={ng.chat_title()}
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="head">
			<span class="title">{ng.chat_title()}</span>
			<!-- Speaking replies needs only the browser, so this appears whenever the voice
			     feature is on -- independently of whether a speech-to-text endpoint exists for
			     the microphone below. -->
			{#if voiceOn && canSpeak}
				<button
					class="speak"
					class:on={speak}
					onclick={toggleSpeak}
					aria-pressed={speak}
					title={ng.chat_voice_speak()}
					aria-label={ng.chat_voice_speak()}
				>
					<Volume2 size={15} />
				</button>
			{/if}
			<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
		</div>

		<div class="list" bind:this={list}>
			{#if chat.bubbles.length === 0}
				<p class="empty">{ng.chat_empty()}</p>
			{/if}

			{#each chat.bubbles as bubble, i (i)}
				{#if bubble.kind === 'user'}
					<div class="bubble user">{bubble.text}</div>
				{:else if bubble.kind === 'assistant'}
					<!-- Plain text, deliberately: the assistant is not asked for markdown and no
					     markdown renderer is loaded, so `pre-wrap` keeps its line breaks without
					     any parsing. Nothing here is ever inserted as HTML. -->
					<div class="bubble assistant">{bubble.text}</div>
				{:else if bubble.kind === 'tool'}
					<!-- A read the assistant did on its own. Shown so its answer is not
					     unexplained; the server writes the summary. -->
					<div class="tool"><Wrench size={12} />{bubble.summary || bubble.name}</div>
				{:else if bubble.kind === 'confirm'}
					{#each bubble.cards as card, ci (ci)}
						<div class="card" class:destructive={card.destructive}>
							<div class="card-title">
								{card.title}
								{#if card.destructive}
									<span class="tag">{ng.chat_confirm_destructive()}</span>
								{/if}
							</div>
							<p class="card-summary">{card.summary}</p>
							<dl class="rows">
								{#each cardRows(card) as row (row.label)}
									<div>
										<dt>{row.label}</dt>
										<dd>
											{#if row.changed}
												<span class="was">{row.before}</span>
												<span class="arrow">→</span>
											{/if}
											<span>{row.after}</span>
										</dd>
									</div>
								{/each}
							</dl>
						</div>
					{/each}
					{#if chat.status === 'awaiting_confirm' && bubble === chat.bubbles[chat.bubbles.length - 1]}
						<div class="decide">
							<Button variant="outline" onclick={() => decide('cancel')}>
								{ng.chat_confirm_cancel()}
							</Button>
							<Button
								variant={chat.pending.some((c) => c.destructive) ? 'danger' : 'primary'}
								onclick={() => decide('confirm')}
							>
								{ng.chat_confirm_confirm()}
							</Button>
						</div>
					{/if}
				{:else if bubble.kind === 'executed'}
					{#each bubble.cards as card, ci (ci)}
						<div class="done-card">
							<span>{card.summary}</span>
							{#if card.undo?.tool}
								<button
									class="undo"
									onclick={() => undo(card, `${i}:${ci}`)}
									disabled={undone.has(`${i}:${ci}`)}
								>
									<Undo2 size={12} />{ng.chat_executed_undo()}
								</button>
							{/if}
						</div>
					{/each}
				{:else if bubble.kind === 'cancelled'}
					<div class="tool">{ng.chat_confirm_cancelled()}</div>
				{:else if bubble.kind === 'error'}
					<div class="bubble error" role="alert">{bubble.text}</div>
				{/if}
			{/each}

			{#if chat.status === 'streaming'}
				<div class="tool" role="status">{ng.chat_thinking()}</div>
			{/if}
		</div>

		<form
			class="composer"
			onsubmit={(e) => {
				e.preventDefault();
				send();
			}}
		>
			<!-- Press and hold, not a toggle: a toggle leaves the microphone live if the user
			     walks away mid-thought. Leaving the button while held cancels, which is how you
			     abandon a recording you have thought better of. -->
			{#if voiceOn && sttReady && canRecord}
				<button
					class="mic"
					class:live={recording}
					onpointerdown={startTalking}
					onpointerup={() => stopTalking(false)}
					onpointerleave={() => recording && stopTalking(true)}
					disabled={transcribing || chat.status !== 'idle'}
					title={ng.chat_voice_record()}
					aria-label={ng.chat_voice_record()}
				>
					<Mic size={15} />
				</button>
			{/if}
			<input
				class="in"
				bind:this={input}
				bind:value={draft}
				placeholder={recording ? ng.chat_voice_listening() : ng.chat_placeholder()}
				disabled={chat.status !== 'idle' || recording || transcribing}
				aria-label={ng.chat_placeholder()}
			/>
			<Button
				variant="primary"
				type="submit"
				disabled={chat.status !== 'idle' || recording || transcribing || !draft.trim()}
			>
				<Send size={14} />
				{ng.chat_send()}
			</Button>
		</form>
	</div>
</div>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.45);
		z-index: 60;
		display: flex;
		justify-content: flex-end;
	}
	.backdrop {
		position: fixed;
		inset: 0;
		border: none;
		margin: 0;
		padding: 0;
		background: transparent;
		cursor: default;
	}
	.drawer {
		position: relative;
		z-index: 1;
		width: 440px;
		max-width: 100%;
		height: 100%;
		display: flex;
		flex-direction: column;
		background: var(--bg);
		border-left: 1px solid var(--border-strong);
		box-shadow: -20px 0 60px rgba(0, 0, 0, 0.5);
	}
	.head {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 16px 20px 12px;
		border-bottom: 1px solid var(--border);
		flex: none;
	}
	.title {
		font-weight: 700;
		font-size: 15px;
	}
	.x {
		margin-left: auto;
		display: inline-flex;
		color: var(--text-dim);
		cursor: pointer;
		padding: 4px 8px;
		background: none;
		border: none;
	}
	.x:hover {
		color: var(--text);
	}
	.list {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 14px 20px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.empty {
		margin: 0;
		font-size: 12.5px;
		line-height: 1.6;
		color: var(--text-muted);
	}
	.bubble {
		padding: 8px 11px;
		border-radius: var(--radius-md);
		font-size: 13px;
		line-height: 1.55;
		white-space: pre-wrap;
		max-width: 90%;
	}
	.bubble.user {
		align-self: flex-end;
		background: var(--bg-hover);
	}
	.bubble.assistant {
		align-self: flex-start;
		background: var(--bg-subtle);
	}
	.bubble.error {
		align-self: stretch;
		max-width: none;
		color: var(--danger);
		background: var(--bg-subtle);
	}
	.tool {
		display: flex;
		align-items: center;
		gap: 5px;
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.card {
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-md);
		padding: 10px 12px;
		background: var(--bg-subtle);
	}
	.card.destructive {
		border-color: var(--danger);
	}
	.card-title {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 13px;
		font-weight: 600;
	}
	.tag {
		font-size: 10.5px;
		color: var(--danger);
		border: 1px solid var(--danger);
		border-radius: var(--radius-sm);
		padding: 1px 5px;
	}
	.card-summary {
		margin: 4px 0 8px;
		font-size: 12.5px;
		color: var(--text-2);
	}
	.rows {
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.rows div {
		display: flex;
		justify-content: space-between;
		gap: 10px;
		font-size: 12px;
	}
	.rows dt {
		color: var(--text-muted);
	}
	.rows dd {
		margin: 0;
		display: flex;
		align-items: center;
		gap: 5px;
		text-align: right;
	}
	.was {
		color: var(--text-dim);
		text-decoration: line-through;
	}
	.arrow {
		color: var(--text-dim);
	}
	.decide {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	.done-card {
		display: flex;
		align-items: center;
		gap: 10px;
		font-size: 12.5px;
		padding: 7px 10px;
		border-radius: var(--radius-sm);
		background: var(--bg-subtle);
	}
	.undo {
		margin-left: auto;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 11.5px;
		color: var(--accent-link);
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
	}
	.undo:disabled {
		color: var(--text-dim);
		cursor: default;
		text-decoration: line-through;
	}
	.speak {
		display: inline-flex;
		color: var(--text-dim);
		cursor: pointer;
		padding: 4px 6px;
		background: none;
		border: none;
		border-radius: var(--radius-sm);
	}
	.speak:hover {
		color: var(--text);
	}
	.speak.on {
		color: var(--accent);
		background: var(--bg-hover);
	}
	.mic {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: 34px;
		color: var(--text-muted);
		background: var(--bg-subtle);
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		/* A held button must not select the surrounding text or fire the browser's own
		   touch-and-hold menu on a phone, which is where this feature is most used. */
		user-select: none;
		touch-action: none;
	}
	.mic:hover:not(:disabled) {
		color: var(--text);
	}
	.mic.live {
		color: var(--danger);
		border-color: var(--danger);
	}
	.mic:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.composer {
		display: flex;
		gap: 8px;
		padding: 12px 20px 16px;
		border-top: 1px solid var(--border);
		flex: none;
	}
	.in {
		flex: 1;
		min-width: 0;
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 7px 10px;
		font-size: 13px;
	}
	.in:focus {
		border-color: var(--accent);
	}
</style>
