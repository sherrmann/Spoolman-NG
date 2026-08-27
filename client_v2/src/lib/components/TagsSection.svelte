<script lang="ts">
	// The NFC/RFID tags linked to a spool, listed in its inspector.
	//
	// A tag is identified by its hardware UID and nothing else, so there is very
	// little to show: the UID, what kind of tag it is when the reader said, and
	// when it was linked. What matters is that the UID shown is the server's
	// canonical spelling — the same physical tag reads as `04:a2:b3:c4` on one
	// reader and `04-A2-B3-C4` on another, and showing whichever spelling happened
	// to be typed would make one tag look like several.
	//
	// Adding is a quiet section action rather than another button in the inspector
	// header: that header already carries the spool's primary actions, and linking
	// a tag is not one of the things you do to a spool every day.
	import SectionLabel from './SectionLabel.svelte';
	import AddTagModal from './AddTagModal.svelte';
	// Spoolman NG fork addition: writing this spool's data ONTO a tag. Upstream links a tag by
	// its UID and never touches what is stored on it, so this has no counterpart here.
	import NfcWriteModal from '$lib/ng/components/NfcWriteModal.svelte';
	import { inventory } from '$lib/stores/inventory.svelte';
	import { ng } from '$lib/ng/i18n';
	import ConfirmDialog from './ConfirmDialog.svelte';
	import Plus from '@lucide/svelte/icons/plus';
	import Nfc from '@lucide/svelte/icons/nfc';
	import X from '@lucide/svelte/icons/x';
	import type { Spool, SpoolTag } from '$lib/types';
	import { unlinkTag } from '$lib/api/tags';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { formatShortDate } from '$lib/utils/datetime';
	import * as m from '$lib/paraglide/messages';

	let { spool }: { spool: Spool } = $props();

	let addOpen = $state(false);
	// Spoolman NG fork addition. The write dialog needs the filament, which a Spool carries only
	// by id; the inspector this section sits in has already loaded it.
	let writeOpen = $state(false);
	let filament = $derived(inventory.filamentById(spool.filamentId));
	let pending = $state<SpoolTag | null>(null);
	let unlinking = $state(false);

	async function confirmUnlink() {
		const tag = pending;
		if (!tag) return;
		unlinking = true;
		try {
			await unlinkTag(spool.id, tag.uid);
			// No local edit: unlinking emits the spool's ordinary `updated` event, and
			// the list below re-renders from the cache when it arrives.
			toasts.success(m['tags.unlinked']());
			pending = null;
		} catch {
			toasts.error(m['tags.unlinkFailed']());
		} finally {
			unlinking = false;
		}
	}
</script>

<SectionLabel>
	{m['tags.section']()}
	{#snippet right()}
		<button class="link" onclick={() => (addOpen = true)}>
			<Plus size={13} />
			{m['tags.add']()}
		</button>
		<!-- Spoolman NG fork addition. Omitted, not disabled, while the filament is missing from
		     the store: `.link` has no disabled styling, so a disabled one is indistinguishable
		     from a live one -- and $lib/utils/nfc states the rule this follows, that a dead
		     button the user cannot explain is worse than no button. The absence is transient;
		     the inspector loads the filament and the control appears with it. -->
		{#if filament}
			<button class="link" onclick={() => (writeOpen = true)}>
				<Nfc size={13} />
				{ng.nfc_encode_button()}
			</button>
		{/if}
	{/snippet}
</SectionLabel>

{#if spool.tags.length}
	<ul class="tags">
		{#each spool.tags as tag (tag.uid)}
			<li class="tag">
				<Nfc size={14} class="ico" />
				<span class="uid mono">{tag.uid}</span>
				{#if tag.format}<span class="fmt">{tag.format}</span>{/if}
				<span class="added">{m['tags.addedOn']({ date: formatShortDate(tag.added) })}</span>
				<button
					class="unlink"
					onclick={() => (pending = tag)}
					title={m['tags.unlink']()}
					aria-label={m['tags.unlink']()}
				>
					<X size={14} />
				</button>
			</li>
		{/each}
	</ul>
{:else}
	<div class="none">{m['tags.none']()}</div>
{/if}

<AddTagModal open={addOpen} {spool} onclose={() => (addOpen = false)} />

<!-- Spoolman NG fork addition. Mounted only while open, like the fork's other dialogs, so it
     starts fresh each time and its abort controller cannot outlive a closed screen. -->
{#if writeOpen && filament}
	<NfcWriteModal {spool} {filament} onclose={() => (writeOpen = false)} />
{/if}

<ConfirmDialog
	open={pending !== null}
	busy={unlinking}
	title={m['tags.unlinkTitle']()}
	lines={pending ? [m['tags.unlinkBody']({ uid: pending.uid })] : []}
	confirmLabel={unlinking ? m['tags.unlinking']() : m['tags.unlink']()}
	onconfirm={confirmUnlink}
	onclose={() => (pending = null)}
/>

<style>
	.link {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 11px;
		color: var(--accent-link);
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
	}
	.link:hover {
		text-decoration: underline;
	}
	.tags {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.tag {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12px;
		padding: 5px 8px;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
	}
	.tag :global(.ico) {
		color: var(--text-dim);
		flex: none;
	}
	.uid {
		font-weight: 600;
		/* The UID is the whole identity of the tag, so it gets the room; everything
		   after it is context and may be dropped on a narrow inspector. */
		overflow-wrap: anywhere;
	}
	.fmt {
		font-size: 10.5px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-muted);
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		padding: 1px 5px;
		flex: none;
	}
	.added {
		margin-left: auto;
		color: var(--text-dim);
		font-size: 11px;
		white-space: nowrap;
	}
	.unlink {
		flex: none;
		display: inline-flex;
		color: var(--text-dim);
		background: none;
		border: none;
		padding: 2px;
		cursor: pointer;
	}
	.unlink:hover {
		color: var(--danger);
	}
	.none {
		font-size: 12px;
		color: var(--text-dim);
	}
</style>
