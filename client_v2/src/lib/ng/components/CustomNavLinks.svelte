<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   These are external URLs an operator typed in. resolve() is for in-app routes: it would
	   prefix the deploy base path onto somebody else's address. */
	/**
	 * Operator-configured links at the end of the nav (#92 / #413).
	 *
	 * Mounted from NavTabs, which TopBar renders on both breakpoints, so one mount covers
	 * desktop and mobile. Renders nothing until the list is known and nothing at all when it is
	 * empty, so an instance without links sees no change. External by definition -- a new tab,
	 * with the referrer and opener withheld, the way the React client opens them.
	 *
	 * Styled to sit beside upstream's `.tab` anchors. Those styles are scoped to NavTabs and do
	 * not reach a child component, so the few rules that matter are restated here.
	 */
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import { navLinks } from '$lib/ng/customLinksState.svelte';

	$effect(() => {
		void navLinks.load();
	});
</script>

{#each navLinks.items as link, i (i)}
	<a class="tab" href={link.url} target="_blank" rel="noopener noreferrer">
		{link.name}
		<ExternalLink size={11} aria-hidden="true" />
	</a>
{/each}

<style>
	.tab {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 6px 12px;
		border-radius: var(--radius);
		font-weight: 400;
		font-size: 13px;
		color: var(--text-dim);
		cursor: pointer;
		user-select: none;
		white-space: nowrap;
		transition:
			background 0.12s ease,
			color 0.12s ease;
	}
	.tab:hover {
		color: var(--text);
		background: var(--accent-wash-soft);
	}
</style>
