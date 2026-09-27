<script lang="ts">
	/**
	 * The phone layout's navigation: a bar along the bottom of the screen, in thumb reach, with
	 * the four most-used pages and a More button. More opens a sheet with every other page, the
	 * operator's custom links and the version and project links.
	 *
	 * It replaced a second header row of sideways-scrolling tabs, which cost ~50px at the top of
	 * every page and hid most of its pages off the edge of the screen. Hidden above the 860px
	 * breakpoint, where the header's own tab row (NavTabs) does this job. Both read their pages
	 * from $lib/ng/nav.
	 */
	import { resolve } from '$app/paths';
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/stores';
	import Menu from '@lucide/svelte/icons/menu';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { NAV_PAGES, isActivePath } from '$lib/ng/nav';
	import LowStockBadge from '$lib/ng/components/LowStockBadge.svelte';
	import CustomNavLinks from '$lib/ng/components/CustomNavLinks.svelte';
	import AboutLinks from '$lib/ng/components/AboutLinks.svelte';

	const primary = NAV_PAGES.filter((p) => p.primary);
	const secondary = NAV_PAGES.filter((p) => !p.primary);

	const basePath = resolve('/').replace(/\/$/, '');
	const isActive = (href: string) => isActivePath(href, $page.url.pathname, basePath);

	let open = $state(false);
	let moreButton: HTMLButtonElement;
	let sheetEl = $state<HTMLDivElement>();

	// "More" reads as the current place while you are on one of the pages it holds.
	let moreActive = $derived(secondary.some((p) => isActive(p.href)));

	function close(restoreFocus = true) {
		if (!open) return;
		open = false;
		if (restoreFocus) moreButton?.focus();
	}

	// Following any link, in the sheet or elsewhere, closes it. Focus goes to the new page.
	afterNavigate(() => close(false));

	$effect(() => {
		if (open) sheetEl?.querySelector<HTMLElement>('a[href]')?.focus();
	});

	function keydown(e: KeyboardEvent) {
		if (!open) return;
		if (e.key === 'Escape') close();
		else if (e.key === 'Tab') keepFocusInSheet(e);
	}

	// The sheet is modal, so Tab must not walk out of it into the page behind the scrim, where a
	// keyboard or switch user could still activate controls. Wrap at both ends, and pull focus
	// back in if it is somehow outside.
	function keepFocusInSheet(e: KeyboardEvent) {
		if (!sheetEl) return;
		const items = Array.from(sheetEl.querySelectorAll<HTMLElement>('a[href], button:not([disabled])'));
		if (items.length === 0) return;
		const first = items[0];
		const last = items[items.length - 1];
		const active = document.activeElement;
		if (!sheetEl.contains(active)) {
			e.preventDefault();
			(e.shiftKey ? last : first).focus();
		} else if (e.shiftKey && active === first) {
			e.preventDefault();
			last.focus();
		} else if (!e.shiftKey && active === last) {
			e.preventDefault();
			first.focus();
		}
	}
</script>

<svelte:window onkeydown={keydown} />

<nav class="bottom-nav">
	{#each primary as item (item.href)}
		{@const Icon = item.icon}
		<a
			href={resolve(item.href)}
			class="item"
			class:active={isActive(item.href)}
			aria-current={isActive(item.href) ? 'page' : undefined}
		>
			<span class="icon"
				><Icon size={22} />{#if item.href === '/lowstock'}<LowStockBadge />{/if}</span
			>
			<span class="label">{item.label()}</span>
		</a>
	{/each}
	<button
		bind:this={moreButton}
		class="item"
		class:active={moreActive || open}
		aria-haspopup="dialog"
		aria-expanded={open}
		onclick={() => (open ? close() : (open = true))}
	>
		<span class="icon"><Menu size={22} /></span>
		<span class="label">{ng.mobile_nav_more()}</span>
	</button>
</nav>

{#if open}
	<!-- The scrim is a pointer-only affordance: keyboard users close with Escape or the close
	     button, so it stays out of the tab order. -->
	<div class="scrim" role="presentation" onclick={() => close()}></div>
	<div
		class="sheet"
		role="dialog"
		aria-modal="true"
		aria-label={ng.mobile_nav_more_pages()}
		bind:this={sheetEl}
	>
		<div class="sheet-head">
			<h2>{ng.mobile_nav_more_pages()}</h2>
			<button class="close" onclick={() => close()} aria-label={m['buttons.close']()}><X size={20} /></button>
		</div>
		<ul class="pages">
			{#each secondary as item (item.href)}
				{@const Icon = item.icon}
				<li>
					<a
						href={resolve(item.href)}
						class="page-link"
						class:active={isActive(item.href)}
						aria-current={isActive(item.href) ? 'page' : undefined}
					>
						<Icon size={20} />
						<span>{item.label()}</span>
					</a>
				</li>
			{/each}
		</ul>
		<div class="custom-links"><CustomNavLinks /></div>
		<section class="about" aria-label={ng.mobile_nav_about()}>
			<AboutLinks compact />
		</section>
	</div>
{/if}

<style>
	.bottom-nav {
		display: none;
	}
	.scrim,
	.sheet {
		display: none;
	}

	@media (max-width: 860px) {
		.bottom-nav {
			flex: none;
			display: flex;
			align-items: stretch;
			height: var(--bottomnav-h);
			/* Clear the home indicator on phones without a physical button row. */
			padding-bottom: env(safe-area-inset-bottom);
			background: var(--surface);
			border-top: 1px solid var(--border);
		}
		.item {
			flex: 1 1 0;
			min-width: 0;
			display: flex;
			flex-direction: column;
			align-items: center;
			justify-content: center;
			gap: 2px;
			padding: 0 2px;
			border: none;
			background: none;
			color: var(--text-dim);
			font: inherit;
			font-size: 11px;
			text-decoration: none;
			cursor: pointer;
		}
		/* Narrow phones: a notch smaller, so single long words ("Bestellungen", "Bibliothèque")
		   still fit a fifth of a 320px screen where the browser cannot hyphenate them. */
		@media (max-width: 360px) {
			.item {
				font-size: 10px;
			}
		}
		@media (max-width: 340px) {
			.item {
				font-size: 9.5px;
				padding: 0;
			}
		}
		.item.active {
			color: var(--accent-soft);
			font-weight: 600;
		}
		.icon {
			position: relative;
			display: inline-flex;
		}
		/* The low-stock count rides on the icon's corner rather than beside the label. */
		.icon :global(.badge) {
			position: absolute;
			top: -6px;
			left: 14px;
			margin: 0;
		}
		/* Up to two lines: in most languages "Low stock" and the like are two words that do not
		   fit a fifth of a phone's width on one line. A single word that is still too long is
		   hyphenated where the browser knows the language, else cut off with an ellipsis. */
		.label {
			max-width: 100%;
			display: -webkit-box;
			-webkit-box-orient: vertical;
			-webkit-line-clamp: 2;
			line-clamp: 2;
			overflow: hidden;
			text-align: center;
			line-height: 1.15;
			hyphens: auto;
		}

		.scrim {
			display: block;
			position: fixed;
			inset: 0;
			/* Above the assistant's floating button (40). */
			z-index: 45;
			background: rgba(0, 0, 0, 0.55);
		}
		.sheet {
			display: flex;
			flex-direction: column;
			gap: 14px;
			position: fixed;
			left: 0;
			right: 0;
			bottom: 0;
			z-index: 46;
			max-height: 85dvh;
			overflow-y: auto;
			overscroll-behavior: contain;
			padding: 14px 16px calc(16px + env(safe-area-inset-bottom));
			background: var(--bg);
			border-top: 1px solid var(--border);
			border-radius: 20px 20px 0 0;
			box-shadow: 0 -12px 40px rgba(0, 0, 0, 0.5);
		}
		.sheet-head {
			display: flex;
			align-items: center;
			justify-content: space-between;
		}
		h2 {
			margin: 0;
			font-size: 15px;
			font-weight: 700;
		}
		.close {
			display: inline-flex;
			align-items: center;
			justify-content: center;
			width: 44px;
			height: 44px;
			margin-right: -10px;
			border: none;
			background: none;
			color: var(--text-2);
			cursor: pointer;
		}
		.pages {
			list-style: none;
			margin: 0;
			padding: 0;
			display: grid;
			grid-template-columns: repeat(2, minmax(0, 1fr));
			gap: 8px;
		}
		.page-link {
			display: flex;
			align-items: center;
			gap: 10px;
			min-height: 48px;
			padding: 0 12px;
			border: 1px solid var(--border);
			border-radius: var(--radius-md);
			background: var(--surface);
			color: var(--text);
			font-size: 14px;
			text-decoration: none;
		}
		.page-link span {
			min-width: 0;
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}
		.page-link.active {
			border-color: var(--accent);
			color: var(--accent-soft);
			font-weight: 600;
		}
		.custom-links {
			display: flex;
			flex-wrap: wrap;
			gap: 4px;
		}
		.custom-links:empty {
			display: none;
		}
		.about {
			padding-top: 12px;
			border-top: 1px solid var(--border);
		}
	}
</style>
