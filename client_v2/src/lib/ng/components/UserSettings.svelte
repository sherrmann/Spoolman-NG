<script lang="ts">
	/**
	 * Account management (#52 / #413): list, create, change role, reset password, delete.
	 *
	 * Administrator-only, and rendered for nobody else: with authentication off the anonymous
	 * caller IS an administrator, which is how the first account gets made. Every refusal the
	 * backend makes -- the last administrator, a duplicate name -- is shown verbatim rather than
	 * second-guessed here.
	 *
	 * Three changes alter what the caller is allowed to do, and the server applies them at
	 * once (spoolman/auth.py re-reads the role map after every account mutation): deleting the
	 * account you are signed in with kills your token; demoting it takes the panels away;
	 * creating the first account switches authentication on. Each of those ends in a reload
	 * rather than a refetch, because a refetch with the credential that has just stopped
	 * working answers 401 beside a toast saying the change succeeded. The delete dialog says
	 * so in advance when it applies to you.
	 *
	 * A role change and a password reset each go through a dialog first. The React client
	 * changes the role on the spot from an inline select; a slipped click there demotes an
	 * administrator, so this one asks.
	 */
	import Button from '$components/Button.svelte';
	import ConfirmDialog from '$components/ConfirmDialog.svelte';
	import KeyRound from '@lucide/svelte/icons/key-round';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { whoAmI, type Me } from '$lib/ng/me';
	import { apiErrorMessage } from '$lib/ng/errors';
	import { clearToken, getToken } from '$lib/ng/authToken';
	import { createUser, deleteUser, listUsers, updateUser } from '$lib/ng/usersApi';
	import { ROLES, isRole, isSelf, validateNewUser, type Role } from '$lib/ng/users';
	import type { User } from '$lib/ng/types';
	import ResetPasswordModal from './ResetPasswordModal.svelte';
	import NgSettingsSection from './NgSettingsSection.svelte';

	let show = $state(false);
	let me = $state<Me | null>(null);
	let users = $state<User[]>([]);
	let hasToken = $state(false);

	const roleLabel: Record<Role, () => string> = {
		admin: ng.auth_roles_admin,
		readonly: ng.auth_roles_readonly
	};

	$effect(() => {
		(async () => {
			me = await whoAmI();
			if (me?.role !== 'admin') return;
			users = await listUsers();
			hasToken = getToken() !== null;
			show = true;
		})().catch(() => {});
	});

	async function refresh() {
		users = await listUsers();
	}

	/** Start over with whatever credential is still valid; the prompt appears if none is. */
	function reload() {
		globalThis.location.reload();
	}

	function logout() {
		clearToken();
		reload();
	}

	// --- create ---------------------------------------------------------------------------
	let newUsername = $state('');
	let newPassword = $state('');
	let newRole = $state<Role>('admin');
	let creating = $state(false);
	let createError = $state('');
	let invalid = $state<'username' | 'password' | null>(null);

	async function create() {
		invalid = validateNewUser(newUsername, newPassword);
		if (invalid) {
			createError = ng.auth_users_need_fields();
			return;
		}
		creating = true;
		createError = '';
		try {
			const username = newUsername.trim();
			const first = users.length === 0;
			await createUser(username, newPassword, newRole);
			toasts.success(ng.auth_users_created({ username }));
			// The first account switches authentication on, so the anonymous session that
			// created it is over: the reload brings up the login prompt.
			if (first) return reload();
			newUsername = '';
			newPassword = '';
			await refresh();
		} catch (e) {
			createError = apiErrorMessage(e);
		} finally {
			creating = false;
		}
	}

	// --- role change ----------------------------------------------------------------------
	// The select the change came from is kept so that a cancelled or refused change can put it
	// back: the list re-renders with the same role string, which the DOM does not treat as a
	// change, so the control would go on showing the value that was never applied.
	let roleChange = $state<{ user: User; role: Role; el: HTMLSelectElement } | null>(null);
	let busy = $state(false);

	function askRole(user: User, el: HTMLSelectElement) {
		const raw = el.value;
		if (!isRole(raw) || raw === user.role) return;
		roleChange = { user, role: raw, el };
	}

	function revertRole() {
		if (roleChange) roleChange.el.value = roleChange.user.role;
		roleChange = null;
	}

	async function applyRole() {
		if (!roleChange) return;
		busy = true;
		try {
			await updateUser(roleChange.user.id, { role: roleChange.role });
			toasts.success(ng.auth_users_role_changed());
			// Your own role decides which panels exist; a reload re-asks.
			if (isSelf(me, roleChange.user)) return reload();
			roleChange = null;
			await refresh();
		} catch (e) {
			toasts.error(apiErrorMessage(e));
			revertRole();
		} finally {
			busy = false;
		}
	}

	// --- password reset -------------------------------------------------------------------
	let resetting = $state<User | null>(null);
	let resetError = $state('');

	async function applyPassword(password: string) {
		if (!resetting) return;
		busy = true;
		resetError = '';
		try {
			await updateUser(resetting.id, { password });
			toasts.success(ng.auth_users_password_reset());
			resetting = null;
		} catch (e) {
			resetError = apiErrorMessage(e);
		} finally {
			busy = false;
		}
	}

	// --- delete ---------------------------------------------------------------------------
	let deleting = $state<User | null>(null);

	async function remove() {
		if (!deleting) return;
		busy = true;
		try {
			const self = isSelf(me, deleting);
			await deleteUser(deleting.id);
			toasts.success(ng.auth_users_deleted());
			// The token just stopped working; keeping it would only earn a 401 prompt.
			if (self) return logout();
			deleting = null;
			await refresh();
		} catch (e) {
			toasts.error(apiErrorMessage(e));
		} finally {
			busy = false;
		}
	}
</script>

{#if show}
	<NgSettingsSection title={ng.auth_users_tab()} description={ng.auth_users_help()}>
		{#if users.length === 0}
			<div class="empty">{ng.auth_users_empty()}</div>
		{:else}
			<ul class="list">
				{#each users as user (user.id)}
					<li class="item">
						<span class="name">
							{user.username}
							{#if isSelf(me, user)}<span class="you">({ng.auth_users_you()})</span>{/if}
						</span>
						<select
							class="in"
							aria-label={`${ng.auth_users_role()}: ${user.username}`}
							value={user.role}
							disabled={busy}
							onchange={(e) => askRole(user, e.currentTarget)}
						>
							{#each ROLES as r (r)}
								<option value={r}>{roleLabel[r]()}</option>
							{/each}
						</select>
						<span class="row-actions">
							<Button
								variant="ghost"
								ariaLabel={`${ng.auth_users_reset_password()}: ${user.username}`}
								title={ng.auth_users_reset_password()}
								onclick={() => {
									resetError = '';
									resetting = user;
								}}><KeyRound size={14} /></Button
							>
							<Button
								variant="danger-ghost"
								ariaLabel={`${m['buttons.delete']()}: ${user.username}`}
								title={m['buttons.delete']()}
								onclick={() => (deleting = user)}><Trash2 size={14} /></Button
							>
						</span>
					</li>
				{/each}
			</ul>
		{/if}

		<form
			class="create"
			onsubmit={(e) => {
				e.preventDefault();
				create();
			}}
		>
			<input
				class="in"
				aria-label={ng.auth_login_username()}
				placeholder={ng.auth_login_username()}
				autocomplete="off"
				bind:value={newUsername}
				class:invalid={invalid === 'username'}
				disabled={creating}
			/>
			<input
				class="in"
				type="password"
				aria-label={ng.auth_login_password()}
				placeholder={ng.auth_login_password()}
				autocomplete="new-password"
				bind:value={newPassword}
				class:invalid={invalid === 'password'}
				disabled={creating}
			/>
			<select class="in" aria-label={ng.auth_users_role()} bind:value={newRole} disabled={creating}>
				{#each ROLES as r (r)}
					<option value={r}>{roleLabel[r]()}</option>
				{/each}
			</select>
			<Button variant="outline" type="submit" disabled={creating}>{ng.auth_users_add()}</Button>
			{#if createError}<div class="error" role="alert">{createError}</div>{/if}
		</form>

		{#snippet after()}
			{#if hasToken}
				<div class="actions">
					<Button variant="outline" onclick={logout}>{ng.auth_logout()}</Button>
				</div>
			{/if}
		{/snippet}
	</NgSettingsSection>

	{#if resetting}
		<ResetPasswordModal
			user={resetting}
			{busy}
			error={resetError}
			onclose={() => (resetting = null)}
			onsubmit={applyPassword}
		/>
	{/if}

	<ConfirmDialog
		open={roleChange !== null}
		{busy}
		title={ng.auth_users_role_change_title()}
		lines={roleChange
			? [
					ng.auth_users_role_change_confirm({
						username: roleChange.user.username,
						role: roleLabel[roleChange.role]()
					})
				]
			: []}
		confirmLabel={ng.auth_users_role_change_title()}
		onconfirm={applyRole}
		onclose={revertRole}
	/>

	<ConfirmDialog
		open={deleting !== null}
		{busy}
		title={ng.auth_users_delete_confirm()}
		lines={deleting
			? [deleting.username, ...(isSelf(me, deleting) ? [ng.auth_users_self_warning()] : [])]
			: []}
		confirmLabel={m['buttons.delete']()}
		onconfirm={remove}
		onclose={() => (deleting = null)}
	/>
{/if}

<style>
	.item {
		grid-template-columns: minmax(0, 1fr) auto auto;
	}
	.name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.you {
		margin-left: 6px;
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.in {
		background: var(--input-bg);
		border: 1px solid var(--border-input);
		border-radius: var(--radius-sm);
		color: var(--text);
		padding: 6px 9px;
		font-size: 12.5px;
	}
	.in:focus {
		border-color: var(--accent);
	}
	.in.invalid {
		border-color: var(--danger);
	}
	.create {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		padding: 10px 14px;
		border-top: 1px solid var(--border);
	}
	.create .in {
		flex: 1 1 140px;
		min-width: 0;
	}
	.error {
		flex-basis: 100%;
		color: var(--danger-soft);
		font-size: 12px;
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		margin-top: 10px;
	}
</style>
