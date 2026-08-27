<script lang="ts">
	/**
	 * Everything the scanner does that upstream's has no notion of (#84 / #97b / #132).
	 *
	 * Rendered inside upstream's QrScannerModal, which keeps owning the camera and the
	 * navigate-to-entity case. This component owns the mode toggle, the two-scan move flow and
	 * the retail-barcode lookup, so the vendored file's only change is to offer each decode here
	 * first. `handleDecode` returns TRUE when it consumed the scan and FALSE to fall through --
	 * which is how navigation stays upstream's: an 'open'-mode scan of a Spoolman code is
	 * declined here and handled by the code that was already there, including whatever upstream
	 * changes about it later.
	 */
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { ui } from '$lib/stores/ui.svelte';
	import { spoolSource } from '$lib/api/spoolSource';
	import { HttpError } from '$lib/api/http';
	import ScanPrompt from './ScanPrompt.svelte';
	import Camera from '@lucide/svelte/icons/camera';
	import ArrowLeftRight from '@lucide/svelte/icons/arrow-left-right';
	import { handleScan } from '../scanActions';
	import { getLocation } from '../api';
	import type { ScanAction } from '../scanMove';

	interface Props {
		/** Called when a scan finishes the job and the scanner should get out of the way. */
		onclose: () => void;
	}
	let { onclose }: Props = $props();

	let action = $state<ScanAction>('open');
	let heldSpoolId = $state<number | null>(null);
	/**
	 * Set while an async branch is in flight, so a burst of camera frames cannot start the same
	 * lookup or move twice. The scanner fires up to five decodes a second and a held label keeps
	 * decoding, so this is the ordinary case rather than a race worth ignoring.
	 */
	let busy = $state(false);

	let move = $state<{ spoolId: number; locationName: string } | null>(null);
	let unknownCode = $state<string | null>(null);

	function setAction(next: ScanAction) {
		action = next;
		// Switching modes abandons a half-finished move: the held spool only means anything
		// inside the flow that captured it.
		heldSpoolId = null;
	}

	export async function handleDecode(raw: string): Promise<boolean> {
		// A dialog is up, or a request is running. Frames keep arriving either way; acting on
		// them would stack a second dialog behind the first.
		if (busy || move !== null || unknownCode !== null) return true;

		busy = true;
		try {
			const effect = await handleScan(raw, action, heldSpoolId, ng.scan_clear_recognized());
			switch (effect.kind) {
				case 'acknowledge':
					toasts.info(effect.message);
					onclose();
					return true;

				case 'outcome':
					switch (effect.outcome.kind) {
						case 'navigate':
							// Upstream's own onDecode does this, and does it better: it knows the
							// routes. Decline the scan rather than restating them here.
							return false;
						case 'capture_spool':
							heldSpoolId = effect.outcome.spoolId;
							return true;
						case 'propose_move': {
							// The confirmation names the location, not its id, so the user can tell
							// they scanned the right shelf. That costs a fetch, which is also what
							// catches a label for a location that has since been deleted.
							const { spoolId, locationId } = effect.outcome;
							try {
								const loc = await getLocation(locationId);
								move = { spoolId, locationName: loc.name };
							} catch {
								toasts.error(ng.scan_move_load_error());
							}
							return true;
						}
						// need_spool / need_location / ignore: deliberately silent. These fire per
						// decoded frame, so a toast would repeat several times a second; the prompt
						// under the mode bar is what tells the user what is expected.
						default:
							return true;
					}

				case 'add_spool':
					// Fetched first, and this is not belt-and-braces: openAddModal seeds itself from
					// the inventory STORE, which is filled from the spool list -- so a filament you
					// own no spools of yet is absent from it, and the modal would open on its search
					// step as though the barcode had matched nothing. That is the likeliest case
					// here, since scanning a manufacturer's barcode is what you do with a spool you
					// have just brought home. fetchFilament upserts into the same store.
					await spoolSource.fetchFilament(effect.filamentId).catch(() => undefined);
					onclose();
					ui.openAddModal(effect.filamentId);
					return true;

				case 'unknown_barcode':
					unknownCode = effect.code;
					return true;

				case 'lookup_failed':
					toasts.error(ng.scan_barcode_lookup_error());
					return true;

				default:
					return true;
			}
		} finally {
			busy = false;
		}
	}

	async function confirmMove() {
		if (move === null) return;
		const { spoolId, locationName } = move;
		busy = true;
		try {
			// `location` on a spool is a plain string, which is what makes this a one-field PATCH
			// rather than a relation change -- see $lib/ng/api's note on the two /location paths.
			await spoolSource.saveSpool(spoolId, { location: locationName });
			toasts.success(ng.scan_move_moved({ spool: spoolId, location: locationName }));
			move = null;
			heldSpoolId = null;
			onclose();
		} catch (e) {
			// Not scan_move_load_error: the location loaded fine, the WRITE failed. Same status-code
			// report the fork's other dialogs give, since there is no reading of a failed PATCH more
			// specific than what the server said.
			toasts.error(m['notifications.error']({ statusCode: e instanceof HttpError ? e.status : '?' }));
			move = null;
		} finally {
			busy = false;
		}
	}

	function createFilamentFor(code: string) {
		unknownCode = null;
		onclose();
		ui.openNewFilamentModal(code);
	}
</script>

<div class="modes" role="group" aria-label={ng.scan_title()}>
	<button class:active={action === 'open'} onclick={() => setAction('open')}>
		<Camera size={14} />{ng.scan_action_open()}
	</button>
	<button class:active={action === 'move'} onclick={() => setAction('move')}>
		<ArrowLeftRight size={14} />{ng.scan_action_move()}
	</button>
</div>

{#if action === 'move'}
	<p class="prompt">
		{#if heldSpoolId === null}
			{ng.scan_move_scan_spool()}
		{:else}
			{ng.scan_move_scan_location({ id: heldSpoolId })}
			<button class="link" onclick={() => (heldSpoolId = null)}>{m['buttons.cancel']()}</button>
		{/if}
	</p>
{/if}

<!--
	Mounted only while there is something to ask, rather than passed an `open` flag: each of
	these carries state that has to start fresh, and only one can ever be up at a time --
	handleDecode declines every frame while either is set.
-->
{#if move !== null}
	<ScanPrompt
		title={ng.scan_move_confirm_title()}
		lines={[ng.scan_move_confirm_content({ spool: move.spoolId, location: move.locationName })]}
		confirmLabel={ng.scan_action_move()}
		onconfirm={confirmMove}
		onclose={() => (move = null)}
		{busy}
	/>
{/if}

{#if unknownCode !== null}
	{@const code = unknownCode}
	<ScanPrompt
		title={ng.scan_barcode_unknown_title()}
		lines={[ng.scan_barcode_unknown_content({ code })]}
		confirmLabel={ng.scan_barcode_create_filament()}
		onconfirm={() => createFilamentFor(code)}
		onclose={() => (unknownCode = null)}
	/>
{/if}

<style>
	.modes {
		display: flex;
		gap: 6px;
		padding: 12px 20px 0;
	}
	.modes button {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		padding: 6px 10px;
		font-size: 12.5px;
		color: var(--text-muted);
		background: var(--bg-subtle);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		cursor: pointer;
	}
	.modes button:hover {
		color: var(--text);
	}
	.modes button.active {
		color: var(--text);
		background: var(--bg-hover);
		border-color: var(--border-strong);
	}
	.prompt {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 20px 0;
		margin: 0;
		font-size: 12.5px;
		color: var(--text-muted);
	}
	.link {
		padding: 0;
		font: inherit;
		color: var(--accent);
		background: none;
		border: none;
		text-decoration: underline;
		cursor: pointer;
	}
</style>
