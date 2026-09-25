<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	// Spoolman NG fork addition: the page list lives in $lib/ng/nav, shared with the phone
	// layout's bottom bar (BottomNav), so a page added here cannot go missing there.
	import { NAV_PAGES as tabs, isActivePath } from '$lib/ng/nav';
	// Spoolman NG fork addition (#417): the low-stock count on the /lowstock tab, mounted below.
	import LowStockBadge from '$lib/ng/components/LowStockBadge.svelte';
	import CustomNavLinks from '$lib/ng/components/CustomNavLinks.svelte';

	// The deploy base path, without its trailing slash (resolve('/') === `${base}/`).
	const basePath = resolve('/').replace(/\/$/, '');

	function isActive(href: string): boolean {
		return isActivePath(href, $page.url.pathname, basePath);
	}

	// Spoolman NG fork addition: when the row is narrower than its tabs (TopBar lets it shrink
	// and scroll), keep the current page's tab in view. Only the row itself is scrolled --
	// scrollIntoView would also scroll the document -- and only on a change of page, not of
	// query string, or every filter change would yank the row back. Re-run when the row's
	// content changes width: the low-stock badge and custom links arrive after first paint.
	let navEl: HTMLElement;
	let pathname = $derived($page.url.pathname);

	function revealActive() {
		const strip = navEl?.parentElement;
		const tab = navEl?.querySelector<HTMLElement>('.tab.active');
		if (!strip || !tab || strip.scrollWidth <= strip.clientWidth) return;
		const left = tab.offsetLeft - strip.offsetLeft;
		if (left < strip.scrollLeft || left + tab.offsetWidth > strip.scrollLeft + strip.clientWidth) {
			strip.scrollTo({ left: left - (strip.clientWidth - tab.offsetWidth) / 2 });
		}
	}

	$effect(() => {
		void pathname;
		revealActive();
	});

	$effect(() => {
		const observer = new ResizeObserver(() => revealActive());
		observer.observe(navEl);
		return () => observer.disconnect();
	});
</script>

<nav class="tabs" bind:this={navEl}>
	{#each tabs as tab (tab.href)}
		<!-- Spoolman NG fork addition (#417): the Low Stock tab carries the count of filaments
		     still needing attention. The badge renders nothing at all until that count is both
		     loaded and non-zero, so every other tab -- and this one while nothing is low -- is
		     exactly what upstream wrote. Written without a line break before the {#if} so the
		     label and the pill are not separated by a stray text node. -->
		<a href={resolve(tab.href)} class="tab" class:active={isActive(tab.href)}
			>{tab.label()}{#if tab.href === '/lowstock'}<LowStockBadge />{/if}</a
		>
	{/each}
	<!-- Spoolman NG fork addition (#413): operator-configured links. Renders nothing unless some exist. -->
	<CustomNavLinks />
</nav>

<style>
	.tabs {
		display: flex;
		gap: 4px;
		align-items: center;
	}
	.tab {
		display: flex;
		align-items: center;
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
	.tab.active {
		font-weight: 600;
		color: var(--accent-soft);
		background: var(--accent-wash);
	}
	.tab.active:hover {
		background: var(--accent-wash);
	}
</style>
