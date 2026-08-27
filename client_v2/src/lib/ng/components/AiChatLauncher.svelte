<script lang="ts">
	/**
	 * The floating button that opens the assistant, and the gate in front of it.
	 *
	 * Renders NOTHING when `ai_feature_chat` is off -- no button, no placeholder, no disabled
	 * state. That is the fork's stated rule for every AI surface ("AI must be invisible unless
	 * explicitly enabled", spoolman/ai.py) and it is also the only honest option: the endpoint
	 * answers 404 while the flag is off, so a visible button would be one that cannot work.
	 *
	 * The check runs once, on mount, and its failure is treated as "off". A settings endpoint
	 * that cannot be reached is not grounds for offering a feature that will fail on click.
	 *
	 * Separate from the drawer so the drawer is only ever constructed when it is actually
	 * opened: it holds an abort controller and a conversation, neither of which should exist
	 * for a user who never presses the button.
	 */
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import { ng } from '$lib/ng/i18n';
	import { chatFeatureEnabled } from '$lib/ng/aiApi';
	import AiChatDrawer from './AiChatDrawer.svelte';

	let enabled = $state(false);
	let open = $state(false);

	$effect(() => {
		const controller = new AbortController();
		chatFeatureEnabled(controller.signal)
			.then((on) => (enabled = on))
			.catch(() => (enabled = false));
		return () => controller.abort();
	});
</script>

{#if enabled}
	<button class="launcher" onclick={() => (open = true)} aria-label={ng.chat_open()} title={ng.chat_open()}>
		<Sparkles size={18} />
	</button>
{/if}

{#if open}
	<AiChatDrawer onclose={() => (open = false)} />
{/if}

<style>
	.launcher {
		position: fixed;
		right: 20px;
		bottom: 20px;
		z-index: 40;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 44px;
		height: 44px;
		border-radius: 50%;
		color: var(--text);
		background: var(--bg-subtle);
		border: 1px solid var(--border-strong);
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
		cursor: pointer;
	}
	.launcher:hover {
		background: var(--bg-hover);
	}
</style>
