<script lang="ts">
	/**
	 * The route-level error page (#417). Fork-owned: upstream has never had a `+error.svelte`,
	 * so this path carries no conflict surface at all.
	 *
	 * SvelteKit renders this for the failures it owns -- a `load` that threw, an explicit
	 * `error()`, and any URL that matches no route. The last is the common one here: the client
	 * is served as a static SPA with a `200.html` fallback, so an unknown path is answered by the
	 * server with the app itself and the 404 is produced by the client router a moment later.
	 *
	 * It does NOT cover an exception thrown while a page component renders; that is caught by the
	 * `<svelte:boundary>` in `+layout.svelte`, which renders the same component.
	 */
	import { page } from '$app/state';
	import ErrorFallback from '$lib/ng/components/ErrorFallback.svelte';
	import { ng } from '$lib/ng/i18n';
</script>

<svelte:head>
	<title>{ng.errorBoundary_title()} | Spoolman</title>
</svelte:head>

<ErrorFallback status={page.status} message={page.error?.message} />
