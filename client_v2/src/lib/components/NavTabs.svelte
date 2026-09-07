<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Pathname } from '$app/types';
	import { page } from '$app/stores';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	// Spoolman NG fork addition (#417): the low-stock count on the /lowstock tab, mounted below.
	import LowStockBadge from '$lib/ng/components/LowStockBadge.svelte';
	import CustomNavLinks from '$lib/ng/components/CustomNavLinks.svelte';

	const tabs = [
		{ href: '/', label: m['nav.library'] },
		// Spoolman NG fork addition. Its label comes from this fork's own message catalogue
		// rather than upstream's, so no string of ours lands in ./locales.
		{ href: '/home', label: ng.home_home },
		// Spoolman NG fork addition (#298), same reasoning as the /home entry above.
		{ href: '/lowstock', label: ng.low_stock_title },
		// Spoolman NG fork addition (#298/#324), same reasoning as the /home entry above.
		{ href: '/orders', label: ng.orders_title },
		{ href: '/dashboard', label: m['dashboard.dashboard'] },
		// Spoolman NG fork addition (#103), same reasoning as the /home entry above.
		{ href: '/locations', label: ng.locations_locations },
		// Spoolman NG fork addition (#123), same reasoning as the /home entry above.
		{ href: '/calibration', label: ng.calibration_title },
		{ href: '/labels', label: m['nav.labels'] },
		{ href: '/settings', label: m['settings.header'] },
		// Spoolman NG fork addition, same reasoning as the /home entry above. Last in the row
		// because it is the one tab nobody navigates to twice.
		{ href: '/help', label: ng.help_help }
	] satisfies { href: Pathname; label: () => string }[];

	// The deploy base path, without its trailing slash (resolve('/') === `${base}/`).
	const basePath = resolve('/').replace(/\/$/, '');

	function isActive(href: string): boolean {
		// Compare against the path with the deploy base path stripped off.
		const path = $page.url.pathname.slice(basePath.length) || '/';
		return href === '/' ? path === '/' : path.startsWith(href);
	}
</script>

<nav class="tabs">
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
