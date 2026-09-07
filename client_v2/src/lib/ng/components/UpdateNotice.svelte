<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   The release link below is an external absolute URL served by the backend's release check;
	   there is no deploy base path to resolve it against. */

	/**
	 * The once-per-release "a new version is available" card (#293) -- the Svelte counterpart of
	 * client/src/components/updateNotification.tsx.
	 *
	 * The backend checks GitHub once a day and reports what it found on `/info`, which the app
	 * already asks for at startup; this reads the answer off `$lib/stores/serverInfo` rather than
	 * fetching anything of its own. Nothing renders until that answer is in, so a slow or failed
	 * `/info` shows nothing rather than flashing a notice and taking it away again.
	 *
	 * Not a toast: the toast store has no sticky mode and dismisses on a timer, and an
	 * announcement that disappears before it is read has not been made. This is a quiet card
	 * instead, dismissed only by the user, at most once per released version.
	 *
	 * What React also offers and this does not: the per-install-type update dialog and the
	 * native self-update trigger (`POST /update`). The link to the release notes is the whole
	 * action here.
	 */
	import Button from '$components/Button.svelte';
	import X from '@lucide/svelte/icons/x';
	import { serverInfo } from '$lib/stores/serverInfo.svelte';
	import { ng } from '$lib/ng/i18n';
	import { rememberUpdateNotice, shouldShowUpdateNotice } from '$lib/ng/updateNotice';

	// Dismissal within this page load. `rememberUpdateNotice` handles every later one, but it
	// writes to storage that may be refusing writes -- the card still has to go away when the
	// close button is pressed.
	let dismissed = $state(false);

	let version = $derived(serverInfo.latestVersion);
	let visible = $derived(
		serverInfo.loaded &&
			!dismissed &&
			shouldShowUpdateNotice(
				{ updateAvailable: serverInfo.updateAvailable, latestVersion: version },
				localStorage
			)
	);

	/** Dismissing and following the link both count as having been told about this version. */
	function acknowledge() {
		if (version) rememberUpdateNotice(version, localStorage);
		dismissed = true;
	}
</script>

{#if visible && version}
	<div class="update-notice" role="status">
		<div class="text">
			<span class="title">{ng.update_notification_title()}</span>
			<span class="description">{ng.update_notification_description({ version })}</span>
			{#if serverInfo.releaseUrl}
				<a
					class="release"
					href={serverInfo.releaseUrl}
					target="_blank"
					rel="noreferrer noopener"
					onclick={acknowledge}
				>
					{ng.update_notification_viewRelease()}
				</a>
			{/if}
		</div>
		<Button variant="ghost" onclick={acknowledge} ariaLabel={ng.update_action_close()}>
			<X size={15} />
		</Button>
	</div>
{/if}

<style>
	/*
	 * Bottom-LEFT, deliberately: the toaster owns the bottom-right corner (right 18px, bottom
	 * 46px) and the assistant launcher the corner below it, so a card there would sit on top of
	 * one or the other. Its z-index is above page content but below every modal overlay (the
	 * add-spool, login and checklist dialogs sit at 50-60) and far below the toaster's 3500: a
	 * dialog that has dimmed the page must cover this card too, and a toast raised while the
	 * notice is up is still the thing on top -- a toast answers something the user just did,
	 * this announces something that happened days ago.
	 */
	.update-notice {
		position: fixed;
		left: 18px;
		bottom: 46px;
		z-index: 45;
		display: flex;
		align-items: flex-start;
		gap: 8px;
		max-width: min(360px, calc(100vw - 36px));
		padding: 10px 10px 10px 14px;
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-lg);
		background: var(--surface-raised);
		color: var(--text);
		font-size: 13px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
	}
	.text {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.title {
		font-weight: 600;
	}
	.description {
		color: var(--text-dim);
	}
	.release {
		margin-top: 2px;
		color: var(--accent);
		font-weight: 600;
		text-decoration: none;
	}
	.release:hover {
		text-decoration: underline;
	}

	/*
	 * Narrow screens: full width like the toaster, and clear above it -- there the toasts are
	 * full-width too and start at bottom 12px, so anything beside them is impossible.
	 */
	@media (max-width: 620px) {
		.update-notice {
			left: 12px;
			right: 12px;
			bottom: 70px;
			max-width: none;
		}
	}
</style>
