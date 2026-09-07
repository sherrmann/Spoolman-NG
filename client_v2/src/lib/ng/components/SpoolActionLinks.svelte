<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   These are external URLs an operator typed in. resolve() is for in-app routes: it would
	   prefix the deploy base path onto somebody else's address. */
	/**
	 * Per-spool action buttons (#140 / #413): one operator-configured link each, with the
	 * spool's fields substituted into the URL.
	 *
	 * Mounted from SpoolInspector below its header. Renders nothing when no links are
	 * configured, so the inspector is unchanged for everyone else. Real anchors rather than
	 * buttons calling window.open: middle-click and copy-link work, and the address is visible
	 * on hover, which is how a wrong template gets noticed.
	 */
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import type { Spool } from '$lib/types';
	import { ng } from '$lib/ng/i18n';
	import { buildSpoolActionUrl } from '$lib/ng/customLinks';
	import { spoolActionLinks } from '$lib/ng/customLinksState.svelte';

	let { spool }: { spool: Spool } = $props();

	$effect(() => {
		void spoolActionLinks.load();
	});
</script>

{#if spoolActionLinks.items.length}
	<div class="links" role="group" aria-label={ng.spool_custom_actions()}>
		{#each spoolActionLinks.items as link, i (i)}
			<a class="btn" href={buildSpoolActionUrl(link.url, spool)} target="_blank" rel="noopener noreferrer">
				<ExternalLink size={13} aria-hidden="true" />
				{link.name}
			</a>
		{/each}
	</div>
{/if}

<style>
	.links {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		padding: 0 0 12px;
	}
	.btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 5px 10px;
		font-size: 12.5px;
		border-radius: var(--radius);
		border: 1px solid var(--border-strong);
		color: var(--text);
		background: transparent;
		text-decoration: none;
		white-space: nowrap;
	}
	.btn:hover {
		background: var(--accent-wash-soft);
	}
</style>
