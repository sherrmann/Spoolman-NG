<script lang="ts">
	/**
	 * Set a new password for an account (#413). Like the React dialog: one field, no repeat, no
	 * old password -- an administrator is resetting somebody's access, not changing their own.
	 */
	import Button from '$components/Button.svelte';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import NgFormModal from './NgFormModal.svelte';
	import type { User } from '$lib/ng/types';

	interface Props {
		user: User;
		busy?: boolean;
		error?: string;
		onclose: () => void;
		onsubmit: (password: string) => void;
	}
	let { user, busy = false, error = '', onclose, onsubmit }: Props = $props();

	let password = $state('');
	let invalid = $state(false);

	function submit() {
		invalid = !password;
		if (invalid) return;
		onsubmit(password);
	}
</script>

<NgFormModal
	title={ng.auth_users_reset_password_for({ username: user.username })}
	{busy}
	{onclose}
	onsubmit={submit}
>
	<p class="help">{ng.auth_users_reset_password_help()}</p>
	<label class="fld">
		<span class="lbl">{ng.auth_login_password()}</span>
		<input
			class="in"
			type="password"
			autocomplete="new-password"
			bind:value={password}
			class:invalid
			aria-invalid={invalid}
			disabled={busy}
		/>
	</label>
	{#if error}<div class="error" role="alert">{error}</div>{/if}
	{#snippet footer()}
		<Button variant="outline" disabled={busy} onclick={onclose}>{m['buttons.cancel']()}</Button>
		<Button variant="primary" type="submit" disabled={busy}>{ng.auth_users_reset_password()}</Button>
	{/snippet}
</NgFormModal>

<style>
	.help {
		margin: 0;
		font-size: 12.5px;
		color: var(--text-muted);
	}
	.fld {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.lbl {
		font-size: 12px;
		color: var(--text-muted);
	}
	.in {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 7px 10px;
		font-size: 13px;
	}
	.in:focus {
		border-color: var(--accent);
	}
	.in.invalid {
		border-color: var(--danger);
	}
	.error {
		color: var(--danger-soft);
		font-size: 12px;
	}
</style>
