// The two custom-link lists (#413), held once and shared by the places that show and edit them.
//
// The nav is mounted twice (desktop and mobile) and lives for the whole session; the settings
// panel that edits the list mounts later. Without a shared store the nav would need a reload
// to show a link that was just added. Each list loads lazily on first use, so a client that
// never renders the nav links pays nothing.

import { getJson } from '$lib/api/http';
import type { SettingResponse } from '$lib/api/settings';
import { parseCustomLinks, type CustomLink } from './customLinks';

export type LinkSettingKey = 'custom_links' | 'spool_action_links';

class LinkList {
	items = $state<CustomLink[]>([]);
	loaded = $state(false);
	private pending: Promise<void> | undefined;

	constructor(private readonly key: LinkSettingKey) {}

	/** Fetch once. Never throws: an unreadable setting is an empty list. */
	load(): Promise<void> {
		this.pending ??= getJson<SettingResponse>(`/setting/${this.key}`)
			.then((s) => {
				this.items = parseCustomLinks(s.value);
			})
			.catch(() => {
				this.items = [];
			})
			.finally(() => {
				this.loaded = true;
			});
		return this.pending;
	}

	/** What the settings panel just saved, so every view agrees without a refetch. */
	replace(items: CustomLink[]): void {
		this.items = items;
		this.loaded = true;
	}
}

export const navLinks = new LinkList('custom_links');
export const spoolActionLinks = new LinkList('spool_action_links');

export function linkList(key: LinkSettingKey): LinkList {
	return key === 'custom_links' ? navLinks : spoolActionLinks;
}
