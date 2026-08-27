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
	import Wrench from '@lucide/svelte/icons/wrench';
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { getLocale } from '$lib/paraglide/runtime';
	import {
		streamChat,
		chatUndo,
		ChatStartError,
		type ChatStartFailure,
		type ChatTurnBody
	} from '$lib/ng/aiApi';
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

	let dialog = $state<HTMLDivElement | null>(null);
	let opener: HTMLElement | null = null;
	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		dialog?.focus();
		input?.focus();
		return () => {
			inFlight?.abort();
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
			<input
				class="in"
				bind:this={input}
				bind:value={draft}
				placeholder={ng.chat_placeholder()}
				disabled={chat.status !== 'idle'}
				aria-label={ng.chat_placeholder()}
			/>
			<Button variant="primary" type="submit" disabled={chat.status !== 'idle' || !draft.trim()}>
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
