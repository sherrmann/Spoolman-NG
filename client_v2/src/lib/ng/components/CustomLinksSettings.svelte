<script lang="ts">
	/**
	 * One list of custom links (#413), mounted twice by NgSettings: once for the nav
	 * (`custom_links`) and once for the per-spool actions (`spool_action_links`). The two differ
	 * only in their copy and in which URL is a template, so they share this component the way
	 * the React client's settings tabs share theirs.
	 *
	 * The whole array is written on every change, because that is the unit the setting stores;
	 * there is no per-row endpoint. After a save the shared store is updated, so the nav shows a
	 * new link without a reload.
	 *
	 * Renders nothing for a non-administrator, who cannot write settings.
	 */
	import Button from '$components/Button.svelte';
	import ConfirmDialog from '$components/ConfirmDialog.svelte';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Plus from '@lucide/svelte/icons/plus';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { setSetting } from '$lib/api/settings';
	import { currentUserIsAdmin } from '$lib/ng/me';
	import { apiErrorMessage } from '$lib/ng/errors';
	import type { CustomLink } from '$lib/ng/customLinks';
	import { linkList, type LinkSettingKey } from '$lib/ng/customLinksState.svelte';
	import LinkFormModal from './LinkFormModal.svelte';
	import NgSettingsSection from './NgSettingsSection.svelte';

	interface Props {
		settingKey: LinkSettingKey;
		title: string;
		/** A `<p>`-wrapped message, as the React catalogue writes it. */
		description: string;
		urlLabel: string;
		urlHelp?: string;
		urlPlaceholder: string;
	}
	let { settingKey, title, description, urlLabel, urlHelp, urlPlaceholder }: Props = $props();

	let list = $derived(linkList(settingKey));
	let show = $state(false);

	$effect(() => {
		(async () => {
			if (!(await currentUserIsAdmin())) return;
			await list.load();
			show = true;
		})().catch(() => {});
	});

	// Editor state: which row the open form is for (-1 = adding), and a pending delete.
	let editing = $state<number | null>(null);
	let deleting = $state<number | null>(null);
	let busy = $state(false);
	let error = $state('');

	async function save(next: CustomLink[]) {
		busy = true;
		error = '';
		try {
			await setSetting(settingKey, next);
			list.replace(next);
			return true;
		} catch (e) {
			error = apiErrorMessage(e);
			toasts.error(error);
			return false;
		} finally {
			busy = false;
		}
	}

	async function submit(link: CustomLink) {
		const next = list.items.slice();
		if (editing === null || editing < 0) next.push(link);
		else next[editing] = link;
		if (await save(next)) editing = null;
	}

	async function remove() {
		if (deleting === null) return;
		const next = list.items.filter((_, i) => i !== deleting);
		if (await save(next)) deleting = null;
	}
</script>

{#if show}
	<NgSettingsSection {title} {description}>
		{#if list.items.length === 0}
			<div class="empty">{ng.settings_custom_links_empty()}</div>
		{:else}
			<ul class="list">
				{#each list.items as link, i (i)}
					<li class="item">
						<span>{link.name}</span>
						<span class="muted mono" title={link.url}>{link.url}</span>
						<span class="row-actions">
							<Button
								variant="ghost"
								ariaLabel={`${m['buttons.edit']()}: ${link.name}`}
								title={m['buttons.edit']()}
								onclick={() => (editing = i)}><Pencil size={14} /></Button
							>
							<Button
								variant="danger-ghost"
								ariaLabel={`${m['buttons.delete']()}: ${link.name}`}
								title={m['buttons.delete']()}
								onclick={() => (deleting = i)}><Trash2 size={14} /></Button
							>
						</span>
					</li>
				{/each}
			</ul>
		{/if}
		<div class="foot">
			<Button variant="outline" onclick={() => (editing = -1)}>
				<Plus size={14} />
				{ng.settings_custom_links_add_title()}
			</Button>
		</div>
	</NgSettingsSection>

	{#if editing !== null}
		<LinkFormModal
			link={editing >= 0 ? list.items[editing] : undefined}
			{urlLabel}
			{urlHelp}
			{urlPlaceholder}
			{busy}
			{error}
			onclose={() => (editing = null)}
			onsubmit={submit}
		/>
	{/if}

	<ConfirmDialog
		open={deleting !== null}
		{busy}
		title={ng.settings_custom_links_delete_confirm()}
		lines={deleting !== null && list.items[deleting] ? [list.items[deleting].name] : []}
		confirmLabel={m['buttons.delete']()}
		onconfirm={remove}
		onclose={() => (deleting = null)}
	/>
{/if}

<style>
	.item {
		grid-template-columns: minmax(80px, 1fr) minmax(0, 2fr) auto;
	}
	@media (max-width: 560px) {
		.item {
			grid-template-columns: 1fr auto;
		}
		.muted {
			grid-column: 1 / -1;
		}
	}
</style>
