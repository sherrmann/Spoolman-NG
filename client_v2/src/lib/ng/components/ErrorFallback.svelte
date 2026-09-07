<script lang="ts">
	/**
	 * What is shown when a page cannot be rendered (#417) -- the Svelte counterpart of
	 * client/src/components/errorBoundary.tsx.
	 *
	 * Used from two places, because SvelteKit and Svelte catch different halves of the problem:
	 * `src/routes/+error.svelte` for a failed `load`, an explicit `error()` and an unknown URL,
	 * and the `<svelte:boundary>` in `src/routes/+layout.svelte` for an exception thrown while a
	 * page component is rendering. Both end here so the two failures read as one thing.
	 *
	 * The recovery on offer is deliberately narrow: forget how the views were laid out, then
	 * reload. See `$lib/ng/viewState` for why that is an allowlist of four keys and not a sweep.
	 *
	 * IMPORTS ARE THE DESIGN HERE. This component must not pull in `library/viewPrefs`,
	 * `dashboard/params`, `stores/collapsedGroups` or `stores/listWidth` -- those read the very
	 * values this page exists to throw away, and several read them at module scope, so importing
	 * one would run the suspect parse inside the page meant to recover from it.
	 */
	import { afterNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import Button from '$components/Button.svelte';
	import { ng } from '$lib/ng/i18n';
	import { clearPersistedViewState } from '$lib/ng/viewState';

	let {
		status,
		message,
		retry
	}: {
		status?: number;
		message?: string;
		/**
		 * The `reset` a `<svelte:boundary>` hands its `failed` snippet. A boundary stays failed
		 * until it is told otherwise, so without this every later client-side navigation -- a nav
		 * tab, the home link below -- would change the URL and leave this panel on screen. Absent
		 * when rendered by +error.svelte, which SvelteKit replaces on navigation by itself.
		 */
		retry?: () => void;
	} = $props();

	// The URL whose page failed. A fallback mounted while a navigation is still completing is
	// registered in time to hear that same navigation's after-callbacks, and retrying there
	// would re-render the page that just threw -- and, if it throws again, mount another
	// fallback inside the same loop. So the retry is only for a navigation that lands
	// somewhere else; the same URL is what the reload button is for.
	const failedHref = page.url.href;

	afterNavigate((nav) => {
		if (retry && nav.to && nav.to.url.href !== failedHref) retry();
	});

	/** `404 · Not Found`, or whichever half of that is actually known. */
	let detail = $derived([status, message].filter(Boolean).join(' · '));

	function reset() {
		clearPersistedViewState(localStorage);
		// A full reload rather than a client-side navigation: the app has already proved it is in
		// a state it cannot render, and only a reload rebuilds every store from the storage that
		// was just cleaned.
		location.reload();
	}
</script>

<div class="error-page">
	<div class="panel" role="alert">
		<h1>{ng.errorBoundary_title()}</h1>
		<p class="subtitle">{ng.errorBoundary_subTitle()}</p>
		{#if detail}
			<!-- The status and the exception's own message, kept quiet and last. It is the only
			     thing on the page that tells a maintainer which failure this was, and the only
			     thing on it a user is not expected to read. -->
			<p class="detail">{detail}</p>
		{/if}
		<div class="actions">
			<Button onclick={reset}>{ng.errorBoundary_reset()}</Button>
			<Button variant="outline" href={resolve('/')}>{ng.errorBoundary_home()}</Button>
		</div>
	</div>
</div>

<style>
	/* Fills whatever the layout's <main> gives it and centres in that, so the page reads the same
	   whether it replaced a route or was raised by the boundary around one. */
	.error-page {
		display: flex;
		flex: 1;
		align-items: center;
		justify-content: center;
		padding: 32px 20px;
		overflow-y: auto;
	}

	.panel {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		max-width: 520px;
		text-align: center;
	}

	h1 {
		margin: 0;
		font-size: 20px;
		font-weight: 600;
		color: var(--text);
	}

	.subtitle {
		margin: 0;
		font-size: 13.5px;
		line-height: 1.5;
		color: var(--text-dim);
	}

	.detail {
		margin: 0;
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--text-faint);
		overflow-wrap: anywhere;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: 10px;
		margin-top: 8px;
	}
</style>
