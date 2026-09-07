<script lang="ts">
	/**
	 * Add or edit one custom link (#413). The caller owns the list and does the saving; this
	 * dialog only produces a validated `{ name, url }`, so the same form serves both the nav
	 * list and the spool-action list.
	 */
	import Button from '$components/Button.svelte';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import NgFormModal from './NgFormModal.svelte';
	import { NAME_MAX, URL_MAX, validateLink, type CustomLink } from '$lib/ng/customLinks';

	interface Props {
		/** The link being edited, or undefined to add one. */
		link?: CustomLink;
		urlLabel: string;
		urlHelp?: string;
		urlPlaceholder: string;
		busy?: boolean;
		error?: string;
		onclose: () => void;
		onsubmit: (link: CustomLink) => void;
	}
	let {
		link,
		urlLabel,
		urlHelp,
		urlPlaceholder,
		busy = false,
		error = '',
		onclose,
		onsubmit
	}: Props = $props();

	// The form starts from the link being edited and then owns its own copy; the caller
	// remounts this dialog per row, so the initial value is the only one that matters.
	// svelte-ignore state_referenced_locally
	let name = $state(link?.name ?? '');
	// svelte-ignore state_referenced_locally
	let url = $state(link?.url ?? '');
	let invalid = $state<'name' | 'url' | null>(null);

	function submit() {
		invalid = validateLink(name, url);
		if (invalid) return;
		onsubmit({ name: name.trim(), url: url.trim() });
	}
</script>

<NgFormModal
	title={link ? ng.settings_custom_links_edit_title() : ng.settings_custom_links_add_title()}
	{busy}
	{onclose}
	onsubmit={submit}
>
	<label class="fld">
		<span class="lbl">{ng.settings_custom_links_name()}</span>
		<input
			class="in"
			bind:value={name}
			maxlength={NAME_MAX}
			class:invalid={invalid === 'name'}
			aria-invalid={invalid === 'name'}
			disabled={busy}
		/>
	</label>
	<label class="fld">
		<span class="lbl">{urlLabel}</span>
		<input
			class="in mono"
			bind:value={url}
			maxlength={URL_MAX}
			placeholder={urlPlaceholder}
			class:invalid={invalid === 'url'}
			aria-invalid={invalid === 'url'}
			disabled={busy}
		/>
		{#if urlHelp}<span class="hint">{urlHelp}</span>{/if}
	</label>
	{#if error}<div class="error" role="alert">{error}</div>{/if}
	{#snippet footer()}
		<Button variant="outline" disabled={busy} onclick={onclose}>{m['buttons.cancel']()}</Button>
		<Button variant="primary" type="submit" disabled={busy}>{m['buttons.save']()}</Button>
	{/snippet}
</NgFormModal>
