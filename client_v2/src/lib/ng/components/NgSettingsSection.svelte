<script lang="ts">
	/**
	 * The chrome every fork settings panel shares: a section landmark named by its title (so a
	 * spec can scope to `getByRole('region', { name })`), the label and intro paragraphs in
	 * upstream's settings style, a Card for the body, and the list styles the bodies use.
	 *
	 * The list rules are `:global` under this section on purpose: the rows are the panel's
	 * markup, not this component's, and three copies of the same forty lines of CSS is how
	 * a spacing fix ends up applied twice. Panels keep only what differs, the grid columns.
	 *
	 * Gating is the panel's job (it also decides what to load), so this renders whatever it is
	 * given; a panel wraps it in `{#if show}`.
	 */
	import Card from '$components/Card.svelte';
	import { parseTrans } from '$lib/ng/trans';
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		/** Plain text, or the `<p>`-wrapped form the React catalogue uses. */
		description?: string;
		children: Snippet;
		/** Anything that belongs below the card, outside it. */
		after?: Snippet;
	}
	let { title, description, children, after }: Props = $props();

	let paragraphs = $derived(
		description
			? parseTrans(description).map((b) => (b.kind === 'block' ? b.inline.map((i) => i.text).join('') : ''))
			: []
	);
</script>

<section class="sec" aria-label={title}>
	<div class="sec-label">{title}</div>
	{#each paragraphs as p, i (i)}<p class="intro">{p}</p>{/each}
	<Card>{@render children()}</Card>
	{#if after}{@render after()}{/if}
</section>

<style>
	.sec-label {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-dim);
		margin: 22px 0 8px;
	}
	.intro {
		margin: 0 0 10px;
		font-size: 12px;
		line-height: 1.55;
		color: var(--text-muted);
	}
	.sec :global(.list) {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.sec :global(.item) {
		display: grid;
		align-items: center;
		gap: 12px;
		padding: 10px 14px;
		font-size: 13px;
	}
	.sec :global(.item + .item) {
		border-top: 1px solid var(--border);
	}
	.sec :global(.muted) {
		color: var(--text-dim);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 12px;
	}
	.sec :global(.row-actions) {
		display: inline-flex;
		gap: 2px;
	}
	.sec :global(.empty) {
		padding: 14px;
		font-size: 12.5px;
		color: var(--text-dim);
	}
	.sec :global(.foot) {
		display: flex;
		justify-content: flex-end;
		padding: 10px 14px;
		border-top: 1px solid var(--border);
	}
</style>
