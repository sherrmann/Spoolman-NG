<script lang="ts">
	import Logo from './Logo.svelte';
	import NavTabs from './NavTabs.svelte';
	import SearchBox from './library/SearchBox.svelte';
	import Button from './Button.svelte';
	import * as m from '$lib/paraglide/messages';
	import Plus from '@lucide/svelte/icons/plus';
	import ScanLine from '@lucide/svelte/icons/scan-line';
	import Search from '@lucide/svelte/icons/search';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import { afterNavigate } from '$app/navigation';

	interface Props {
		onadd?: () => void;
		onscan?: () => void;
	}

	let { onadd, onscan }: Props = $props();

	// On mobile the search field would otherwise need its own row. Instead it
	// collapses to a single icon in the top row and, when tapped, expands into a
	// full-width overlay covering the logo/scan/add controls — so what you type
	// stays fully visible while the top bar keeps to two rows (controls + nav).
	let searchOpen = $state(false);
	let overlayEl = $state<HTMLDivElement>();

	function openSearch() {
		searchOpen = true;
		// Focus the field once the overlay has painted.
		requestAnimationFrame(() => overlayEl?.querySelector('input')?.focus());
	}
	function closeSearch() {
		searchOpen = false;
	}
	// Collapse once a result (or any nav) has been followed.
	afterNavigate(() => (searchOpen = false));
</script>

<header class="topbar">
	<div class="row primary" class:searching={searchOpen}>
		<Logo />
		<div class="nav-desktop"><NavTabs /></div>
		<div class="spacer"></div>
		<button
			class="search-toggle"
			onclick={openSearch}
			aria-label={m['common.search']()}
			title={m['common.search']()}
		>
			<Search size={18} />
		</button>
		<button class="scan-btn" onclick={onscan} aria-label={m['scanner.title']()} title={m['scanner.title']()}>
			<ScanLine size={18} />
		</button>
		<button
			class="add-mobile"
			onclick={onadd}
			aria-label={m['topbar.addSpools']()}
			title={m['topbar.addSpools']()}
		>
			<Plus size={18} />
		</button>
		<div class="search-desktop">
			<SearchBox />
		</div>
		<div class="add-desktop">
			<Button onclick={onadd}><Plus size={15} /> {m['topbar.addSpools']()}</Button>
		</div>

		<!-- Mobile: the expanded search overlays the row so the typed query is visible. -->
		<div class="search-overlay" bind:this={overlayEl}>
			<button class="search-back" onclick={closeSearch} aria-label={m['buttons.close']()}>
				<ArrowLeft size={20} />
			</button>
			<SearchBox fullWidth />
		</div>
	</div>

	<!-- Spoolman NG fork addition: upstream's second row of scrolling tabs for phones is gone.
	     It cost ~50px at the top of every page and hid most pages past the screen's edge; the
	     bottom navigation (BottomNav, mounted by the layout) replaces it. -->
</header>

<style>
	.topbar {
		flex: none;
		background: var(--surface);
		border-bottom: 1px solid var(--border);
	}
	.row {
		display: flex;
		align-items: center;
		gap: 20px;
		padding: 0 18px;
	}
	.row.primary {
		height: var(--topbar-h);
	}
	.spacer {
		flex: 1;
	}
	.scan-btn {
		flex: none;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-strong);
		background: none;
		color: var(--text-2);
		cursor: pointer;
	}
	.scan-btn:hover {
		color: var(--text);
		border-color: var(--accent);
	}

	/* Collapsed mobile search trigger and its expanded overlay: hidden until the
	   mobile breakpoint (desktop uses the always-visible .search-desktop field). */
	.add-mobile,
	.search-toggle,
	.search-overlay {
		display: none;
	}

	/* Spoolman NG fork addition: with this fork's extra pages the tab row alone is ~850px, and
	   below ~1500px the header was wider than the window -- the search field, scan button and
	   "Add spools" sat past its right edge, reachable only by scrolling the whole page sideways.
	   Below 1500px the search collapses to the icon and overlay the phone layout uses, and the
	   tabs scroll inside their own space rather than pushing the actions off the screen. */
	@media (max-width: 1499px) {
		.nav-desktop {
			flex: 0 1 auto;
			min-width: 0;
			overflow-x: auto;
			scrollbar-width: none;
		}
		.search-desktop {
			display: none;
		}
		.row.primary {
			/* Anchor the absolutely-positioned search overlay. */
			position: relative;
		}
		/* Search and scan are peer secondary actions, so they share the outlined
		   icon-button look; the filled + button stays the primary action. */
		.search-toggle {
			flex: none;
			display: inline-flex;
			align-items: center;
			justify-content: center;
			width: 36px;
			height: 36px;
			border-radius: var(--radius-md);
			border: 1px solid var(--border-strong);
			background: none;
			color: var(--text-2);
			cursor: pointer;
		}
		.search-toggle:hover {
			color: var(--text);
			border-color: var(--accent);
		}
		.search-overlay {
			position: absolute;
			inset: 0;
			align-items: center;
			gap: 6px;
			padding: 0 12px;
			background: var(--surface);
			z-index: 5;
		}
		.row.primary.searching .search-overlay {
			display: flex;
		}
		.search-overlay :global(.search-box) {
			flex: 1;
			min-width: 0;
		}
		.search-back {
			flex: none;
			display: inline-flex;
			align-items: center;
			justify-content: center;
			width: 44px;
			height: 44px;
			border: none;
			background: none;
			color: var(--text-2);
			cursor: pointer;
		}
		.search-back:hover {
			color: var(--text);
		}
	}

	@media (max-width: 860px) {
		.nav-desktop,
		.add-desktop {
			display: none;
		}
		.row.primary {
			gap: 12px;
		}
		.search-toggle,
		.scan-btn {
			width: 44px;
			height: 44px;
		}
		.add-mobile {
			flex: none;
			display: inline-flex;
			align-items: center;
			justify-content: center;
			width: 44px;
			height: 44px;
			border-radius: var(--radius-md);
			border: none;
			background: var(--accent-fill);
			color: #fff;
			cursor: pointer;
		}
	}

	/* Spoolman NG fork addition: below 360px (iPhone SE, small Android) the wordmark plus three
	   44px buttons is wider than the screen, which pushed the add button off the edge and made
	   every page scroll sideways. The mark alone still links home and keeps its aria-label. */
	@media (max-width: 359px) {
		.row.primary :global(.logo span) {
			display: none;
		}
	}
</style>
