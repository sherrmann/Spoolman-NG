/**
 * Whether to announce a newer release, and remembering that it has been announced (#293).
 *
 * The backend checks for a new release once a day and reports the answer on `/info`
 * (`update_available`, `latest_version`, `release_url`). The notice built on top of that has
 * to fire at most once per release: dismissing it must keep it quiet until an even newer
 * version ships, and it must not come back on every navigation or reload in between.
 *
 * Pure so it can be tested without a DOM; the card itself is
 * `$lib/ng/components/UpdateNotice.svelte`.
 */

/**
 * Where the newest already-announced version is remembered.
 *
 * This is the React client's own literal (`client/src/components/updateNotification.tsx`), and
 * deliberately so: both clients are served from the same origin and share one localStorage, so
 * a user who dismisses the notice in one and then switches interface -- which this fork invites
 * them to do (#405) -- would otherwise be told about the same release a second time. The same
 * argument as `authToken.ts` shares `spoolmanApiToken`: the value means exactly the same thing
 * on both sides, so it is one key, not two.
 */
export const UPDATE_NOTIFIED_KEY = 'spoolman-update-notified';

/**
 * Whether the notice should be shown at all.
 *
 * False unless the server both reports an update and names the version it found: the version is
 * what the description says and what dismissal records, so an update with no version has nothing
 * to announce and no way to be silenced. False again once that exact version has been dismissed;
 * a *newer* version passes, because what was stored is an older string.
 */
export function shouldShowUpdateNotice(
	info: { updateAvailable: boolean; latestVersion: string | null },
	storage: Storage | undefined
): boolean {
	if (!info.updateAvailable || !info.latestVersion) return false;
	try {
		return storage?.getItem(UPDATE_NOTIFIED_KEY) !== info.latestVersion;
	} catch {
		// Private browsing and "block site data" both throw here. Showing the notice for this
		// session is the right failure: an announcement that cannot be remembered is a small
		// annoyance, one that cannot be made is a missed security update.
		return true;
	}
}

/** Record that this version has been announced, so it is not announced again. */
export function rememberUpdateNotice(version: string, storage: Storage | undefined): void {
	try {
		storage?.setItem(UPDATE_NOTIFIED_KEY, version);
	} catch {
		// As above: the dismissal simply does not stick, and the notice returns on the next load.
	}
}
