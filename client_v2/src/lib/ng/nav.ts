/**
 * The app's pages, in navigation order, and the project links that used to live in the footer.
 *
 * One list for both navigations: the desktop tab row (NavTabs) and the phone layout's bottom bar
 * with its More sheet (BottomNav). Keeping them apart would let a page added to one quietly go
 * missing from the other -- on a phone, that page would simply be unreachable.
 */
import type { Component } from 'svelte';
import type { Pathname } from '$app/types';
import * as m from '$lib/paraglide/messages';
import { ng } from '$lib/ng/i18n';
import LibraryBig from '@lucide/svelte/icons/library-big';
import House from '@lucide/svelte/icons/house';
import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
import ShoppingCart from '@lucide/svelte/icons/shopping-cart';
import LayoutDashboard from '@lucide/svelte/icons/layout-dashboard';
import MapPin from '@lucide/svelte/icons/map-pin';
import FlaskConical from '@lucide/svelte/icons/flask-conical';
import Tag from '@lucide/svelte/icons/tag';
import Settings from '@lucide/svelte/icons/settings';
import CircleQuestionMark from '@lucide/svelte/icons/circle-question-mark';

export interface NavPage {
	href: Pathname;
	label: () => string;
	icon: Component<{ size?: number }>;
	/** Shown in the phone layout's bottom bar; the rest go under More. */
	primary: boolean;
}

export const NAV_PAGES: NavPage[] = [
	{ href: '/', label: m['nav.library'], icon: LibraryBig, primary: true },
	// Fork pages take their labels from this fork's own message catalogue rather than
	// upstream's, so no string of ours lands in ./locales.
	{ href: '/home', label: ng.home_home, icon: House, primary: true },
	{ href: '/lowstock', label: ng.low_stock_title, icon: TriangleAlert, primary: true },
	{ href: '/orders', label: ng.orders_title, icon: ShoppingCart, primary: true },
	{ href: '/dashboard', label: m['dashboard.dashboard'], icon: LayoutDashboard, primary: false },
	{ href: '/locations', label: ng.locations_locations, icon: MapPin, primary: false },
	{ href: '/calibration', label: ng.calibration_title, icon: FlaskConical, primary: false },
	{ href: '/labels', label: m['nav.labels'], icon: Tag, primary: false },
	{ href: '/settings', label: m['settings.header'], icon: Settings, primary: false },
	// Last: the one page nobody navigates to twice.
	{ href: '/help', label: ng.help_help, icon: CircleQuestionMark, primary: false }
];

/**
 * Whether `href` is the page at `pathname`. `basePath` is the deploy base path without its
 * trailing slash, which is stripped before comparing; the library ("/") matches only itself,
 * every other page also matches its sub-paths (/location/show/3 is not /locations, though).
 */
export function isActivePath(href: string, pathname: string, basePath: string): boolean {
	const path = pathname.slice(basePath.length) || '/';
	return href === '/' ? path === '/' : path.startsWith(href);
}

/** This fork's repository: documentation is its README, problems go to its issue tracker. */
export const PROJECT_LINKS = {
	documentation: 'https://github.com/sherrmann/Spoolman-NG#readme',
	issues: 'https://github.com/sherrmann/Spoolman-NG/issues',
	// Credit to the original author of Spoolman, as upstream's footer gave it.
	sponsor: 'https://github.com/sponsors/Donkie'
} as const;
