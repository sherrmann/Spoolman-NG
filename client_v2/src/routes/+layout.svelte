<script lang="ts">
	import '../app.css';
	import TopBar from '$components/TopBar.svelte';
	// Spoolman NG fork addition: upstream's footer is gone; its version and links moved to the
	// Help page and the phone layout's More sheet (AboutLinks). BottomNav is the phone layout's
	// navigation, in the footer's place at the bottom of the shell.
	import BottomNav from '$lib/ng/components/BottomNav.svelte';
	import AddSpoolModal from '$components/AddSpoolModal.svelte';
	import QrScannerModal from '$components/QrScannerModal.svelte';
	import AiChatLauncher from '$lib/ng/components/AiChatLauncher.svelte';
	import UpdateNotice from '$lib/ng/components/UpdateNotice.svelte';
	import ErrorFallback from '$lib/ng/components/ErrorFallback.svelte';
	import LoginModal from '$lib/ng/components/LoginModal.svelte';
	import { authState } from '$lib/ng/authState.svelte';
	import { loadUnitScaling } from '$lib/ng/unitScaling.svelte';
	import Toaster from '$components/Toaster.svelte';
	import { ui } from '$lib/stores/ui.svelte';
	import { settings } from '$lib/stores/settings.svelte';
	import { serverInfo } from '$lib/stores/serverInfo.svelte';
	import { theme } from '$lib/stores/theme.svelte';
	import { startLiveSync } from '$lib/api/liveSync';
	import { scanRelay } from '$lib/api/scanRelay';
	import { scanner, isBrowsableRoute } from '$lib/stores/scanner.svelte';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { inventory } from '$lib/stores/inventory.svelte';
	import { getLocale, getTextDirection } from '$lib/paraglide/runtime';
	import { openSearchResult } from '$lib/library/params';
	import { filamentLabel } from '$lib/utils/library';
	import { page } from '$app/state';
	import * as m from '$lib/paraglide/messages';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	// Keep <html data-theme> in sync with the preference (and OS changes when set
	// to "system"). The initial paint is already themed by the inline script in
	// app.html; this takes over once the app hydrates.
	$effect(() => {
		theme.apply();
	});

	// Reflect the resolved locale onto <html lang>/<dir>. app.html ships a static
	// "en"/"ltr" default (SSR is off, so the paraglide placeholders would never be
	// substituted); this applies the real locale once the app hydrates. Changing
	// the language reloads the page, so reading getLocale() once at mount is enough.
	$effect(() => {
		document.documentElement.lang = getLocale();
		document.documentElement.dir = getTextDirection();
	});

	// Load server settings and start central live-sync (keeps the reactive cache,
	// and thus every view that reads it, up to date with WebSocket events).
	$effect(() => {
		settings.load();
		serverInfo.load();
		// Asks the open /auth/status route what this server wants, so the prompt
		// below knows which form to show before anything has been refused.
		authState.load();
		// Spoolman NG fork addition: whether large weights show in kilograms (#413).
		loadUnitScaling();

		return startLiveSync();
	});

	// The one place a scanned tag is allowed to move this browser.
	//
	// Exactly one subscription, and it lives here rather than in whichever
	// component happens to care, because two mounted components reacting to the
	// same scan is how one tap becomes two navigations. Dialogs that need scans
	// (AddTagModal) subscribe for their own purposes but never navigate.
	//
	// It exists only while auto-navigate is on, which also means a browser that
	// isn't using NFC holds no relay socket at all. Re-runs when the paired reader
	// changes, moving the subscription to the new pool.
	$effect(() => {
		if (!scanner.autoNavigate) return;
		return scanRelay.subscribe(scanner.pool, (scan) => {
			scanner.receive(scan);
			// Read inside the handler, never in the effect body: depending on the route
			// here would tear the socket down and rebuild it on every navigation.
			// A page you are configuring reacts to nothing — not even the toast, which
			// during pairing would explain how to link the tag you just tapped to pair.
			if (!isBrowsableRoute(page.route.id)) return;
			// A tag identifies a spool or a filament, and either opens in the inspector.
			const hit = scan.spool
				? { kind: 'spool' as const, id: String(scan.spool.id) }
				: scan.filament
					? { kind: 'filament' as const, id: scan.filament.id }
					: null;
			if (!hit) {
				// An unknown tag has nowhere to navigate to, and silently ignoring it
				// would look like the tap failed. Say what was read and where to link
				// it — repeats coalesce, and the relay already debounces a reader that
				// re-reads a tag left sitting on it. Not an error: tapping a tag no
				// spool claims yet is how enrolling one starts.
				toasts.info(m['tags.scan.unknown']({ uid: scan.uid }));
				return;
			}
			if (!scanner.mayNavigate(document.activeElement, ui.addModalOpen || ui.scannerOpen)) return;
			// The same navigation a picked search result gets, and for the same reason:
			// on the Library it merges the selection into the view you are already in,
			// so a tap reveals the spool without throwing away the grouping, sort and
			// filters you had set up; from anywhere else it opens the Library on just
			// that spool. The inspector resolves a selection by id on its own, so the
			// spool still opens when the active filters exclude it from the list behind
			// it -- a scan answers "where is this spool", never "is it in this view".
			openSearchResult(hit.kind, hit.id);
			// Say what the tap did. The reader is often in another room from the screen,
			// and a page that changes by itself with no word why reads as a glitch. The
			// relay already cached the spool's filament and vendor, so naming is local.
			const filament = scan.filament ?? inventory.filamentById(scan.spool?.filamentId ?? '');
			const name = filament ? filamentLabel(filament, inventory.vendorById(filament.vendorId)) : '';
			toasts.info(
				scan.spool
					? m['tags.scan.openedSpool']({ id: scan.spool.id, name })
					: m['tags.scan.openedFilament']({ name })
			);
		});
	});
</script>

<div class="app">
	<TopBar onadd={() => ui.openAddModal()} onscan={() => ui.openScanner()} />

	<main>
		<!-- Spoolman NG fork addition: the render-time error boundary (#417). SvelteKit sends a
		     failed `load`, an explicit error() and an unknown URL to +error.svelte, but NOT an
		     exception thrown while a page component renders -- which is exactly where a corrupt
		     persisted value blows up -- and this layout is the only place that wraps every page.
		     The fallback is the same component +error.svelte renders. -->
		<svelte:boundary onerror={(error) => console.error('Uncaught render error:', error)}>
			{@render children()}
			{#snippet failed(error, reset)}
				<ErrorFallback message={error instanceof Error ? error.message : String(error)} retry={reset} />
			{/snippet}
		</svelte:boundary>
	</main>
	<BottomNav />
</div>

<AddSpoolModal
	open={ui.addModalOpen}
	presetFilamentId={ui.addModalFilamentId}
	duplicateFilamentId={ui.addModalDuplicateId}
	presetArticleNumber={ui.addModalArticleNumber}
	onclose={() => ui.closeAddModal()}
/>

<QrScannerModal open={ui.scannerOpen} onclose={() => ui.closeScanner()} />

<!-- Spoolman NG fork addition: the assistant. Renders nothing at all -- not even its button --
     unless an operator has switched the feature on; see AiChatLauncher. -->
<AiChatLauncher />

<!-- Spoolman NG fork addition: the once-per-release update notice (#293). Renders nothing until
     /info has answered, and nothing at all unless that answer names a newer version the user has
     not already dismissed. -->
<UpdateNotice />

<!-- Raised when a request comes back asking for credentials we do not have (#406).
     Conditionally mounted, like the fork's other dialogs, so each prompt starts
     with empty fields rather than whatever the last attempt left behind. -->
{#if authState.prompting}
	<LoginModal onclose={() => (authState.prompting = false)} />
{/if}

<Toaster />

<style>
	.app {
		display: flex;
		flex-direction: column;
		height: 100vh;
		height: 100dvh;
		background: var(--bg);
		color: var(--text);
	}

	main {
		display: flex;
		flex: 1;
		min-height: 0;
	}
</style>
