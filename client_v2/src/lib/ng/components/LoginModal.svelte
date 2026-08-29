<script lang="ts">
	/**
	 * Ask for the credential the server just refused us for (#406).
	 *
	 * Two forms behind one dialog, chosen by what GET /auth/status reports rather
	 * than by asking the user which kind of instance they are on:
	 *
	 *   accounts enabled   username and password, exchanged for a token by
	 *                      POST /auth/login.
	 *   otherwise          the operator's shared SPOOLMAN_API_TOKEN, taken at face
	 *                      value -- there is nothing to validate it against short
	 *                      of making a real request, which is what happens next.
	 *
	 * Dismissible, like the React client's equivalent. The app behind is not usable
	 * without a credential, but trapping someone in a dialog they opened by
	 * accident is worse than letting them out; the next refused request raises it
	 * again.
	 */
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { authState } from '$lib/ng/authState.svelte';

	interface Props {
		onclose: () => void;
	}
	let { onclose }: Props = $props();

	let username = $state('');
	let password = $state('');
	let token = $state('');
	let busy = $state(false);
	/** The last attempt's reason for failing, kept beside the form rather than toasted. */
	let error = $state('');

	let dialog = $state<HTMLDivElement>();
	let firstField = $state<HTMLInputElement>();
	let opener: HTMLElement | null = null;

	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		// Focus the field, not the dialog: this one exists to be typed into.
		(firstField ?? dialog)?.focus();
		return () => opener?.focus();
	});

	function close() {
		if (busy) return;
		onclose();
	}

	const canSubmit = $derived(
		authState.accountsEnabled ? username.trim() !== '' && password !== '' : token.trim() !== ''
	);

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		if (busy || !canSubmit) return;
		busy = true;
		error = '';
		try {
			if (authState.accountsEnabled) {
				// Reloads the page on success, so nothing after this runs.
				await authState.login(username.trim(), password);
			} else {
				authState.acceptToken(token);
			}
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
			busy = false;
		}
	}
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && close()} />

<div class="overlay">
	<!-- A sibling of the dialog rather than its parent, so interactive controls are not nested
	     inside an interactive element. -->
	<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={close}></button>
	<div
		class="modal"
		role="dialog"
		aria-modal="true"
		aria-labelledby="login-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="login-title">
				{authState.accountsEnabled ? ng.auth_login_title() : ng.apiToken_title()}
			</span>
			<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
		</div>

		<form class="body" onsubmit={submit}>
			{#if authState.accountsEnabled}
				<label class="fld">
					<span class="lbl">{ng.auth_login_username()}</span>
					<input bind:this={firstField} bind:value={username} autocomplete="username" disabled={busy} />
				</label>
				<label class="fld">
					<span class="lbl">{ng.auth_login_password()}</span>
					<input type="password" bind:value={password} autocomplete="current-password" disabled={busy} />
				</label>
			{:else}
				<p class="note">{ng.apiToken_help()}</p>
				<label class="fld">
					<span class="lbl">{ng.apiToken_placeholder()}</span>
					<input
						bind:this={firstField}
						type="password"
						bind:value={token}
						autocomplete="off"
						spellcheck="false"
						disabled={busy}
					/>
				</label>
			{/if}

			{#if error}
				<p class="error" role="alert">{error}</p>
			{/if}

			<div class="foot">
				<button class="primary" type="submit" disabled={busy || !canSubmit}>
					{authState.accountsEnabled ? ng.auth_login_submit() : ng.apiToken_submit()}
				</button>
			</div>
		</form>
	</div>
</div>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		z-index: 60;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding: 8vh 16px 16px;
	}
	.backdrop {
		position: fixed;
		inset: 0;
		border: none;
		margin: 0;
		padding: 0;
		background: transparent;
		cursor: default;
	}
	.modal {
		position: relative;
		z-index: 1;
		width: 420px;
		max-width: 100%;
		max-height: 84vh;
		display: flex;
		flex-direction: column;
		background: var(--bg);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-xl);
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
		overflow: hidden;
	}
	.modal-head {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 16px 20px 0;
		flex: none;
	}
	.title {
		font-weight: 700;
		font-size: 15px;
	}
	.x {
		margin-left: auto;
		display: inline-flex;
		color: var(--text-dim);
		cursor: pointer;
		padding: 4px 8px;
		background: none;
		border: none;
	}
	.x:hover {
		color: var(--text);
	}
	.body {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 16px 20px;
		overflow-y: auto;
	}
	.note {
		margin: 0;
		font-size: 13px;
		color: var(--text-dim);
	}
	.error {
		margin: 0;
		font-size: 13px;
		color: var(--danger, #e5484d);
	}
	.fld {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.lbl {
		font-size: 12px;
		color: var(--text-dim);
	}
	.fld input {
		padding: 8px 10px;
		background: var(--bg-elevated, var(--bg));
		color: var(--text);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-md, 8px);
		font: inherit;
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		padding-top: 4px;
	}
	.primary {
		padding: 8px 16px;
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-md, 8px);
		background: var(--accent, #dc7734);
		color: #fff;
		font: inherit;
		cursor: pointer;
	}
	.primary:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
