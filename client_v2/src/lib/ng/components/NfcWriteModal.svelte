<script lang="ts">
	/**
	 * Write a spool's data onto an NFC tag (#97) -- ported from the React client's
	 * nfcWriteModal.tsx.
	 *
	 * Three routes to a written tag, and they are not interchangeable, which is most of what this
	 * dialog exists to communicate:
	 *
	 *   Server   a reader attached to the Spoolman host writes the raw bytes. The only route that
	 *            produces a tag the TigerTag app recognises, and the only one that can write Qidi
	 *            at all -- MIFARE Classic is out of Web NFC's reach.
	 *   Browser  this phone writes over Web NFC, which can only emit NDEF. The payload is
	 *            identical and the tag is still not recognised, because the app reads raw bytes
	 *            from NTAG213 pages 4-39 and NDEF puts them elsewhere. The wrapping is the ONLY
	 *            difference: measured against a running backend, this codec's output matches the
	 *            server's byte for byte but for the timestamp. See the note on the download
	 *            button below, which had been written on the opposite assumption.
	 *   Download the same bytes as a file, for a desktop or iOS user whose browser has no Web NFC
	 *            and who will take them to an external tool. Needs no reader and no radio, so it
	 *            is offered whenever the other two are not.
	 *
	 * Mounted only while a spool is chosen, like the fork's other dialogs, so there is no `open`
	 * prop and nothing to reset between uses.
	 */
	import Button from '$components/Button.svelte';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { nfcStatus, nfcWrite, nfcEncode, type TagFormat } from '$lib/ng/nfcApi';
	import { writeTigerTagNdef } from '$lib/ng/nfcWrite';
	import { encodeTigerTag, mapSpoolToTigerTag } from '$lib/ng/tigertagCodec';
	import { nfcSupported, NfcError } from '$lib/utils/nfc';
	import type { Spool, Filament } from '$lib/types';

	interface Props {
		spool: Spool;
		filament: Filament;
		onclose: () => void;
	}
	let { spool, filament, onclose }: Props = $props();

	type Mode = 'server' | 'browser';

	let mode = $state<Mode>('server');
	let tagFormat = $state<TagFormat>('tigertag');
	let userMessage = $state('');
	let busy = $state(false);
	/** The last attempt's outcome, kept on screen rather than toasted: it is the dialog's answer. */
	let result = $state<{ ok: boolean; message: string } | null>(null);

	/** Whether the host has a reader. Undefined until the status call answers. */
	let readerReady = $state<boolean | undefined>(undefined);
	const browserReady = nfcSupported();

	let dialog = $state<HTMLDivElement>();
	let opener: HTMLElement | null = null;
	/**
	 * One AbortSignal for the whole dialog. A browser write keeps the radio live until a tag is
	 * tapped, so closing without aborting would leave it running behind a screen nobody is
	 * looking at -- the same requirement $lib/utils/nfc states for reading.
	 */
	let writeAbort: AbortController | null = null;

	$effect(() => {
		opener = document.activeElement as HTMLElement | null;
		dialog?.focus();
		nfcStatus().then((s) => {
			readerReady = s.enabled && s.status === 'connected';
			// Land on a mode that can actually do something. Server is the better tag and so the
			// default when it is available; otherwise the browser, if this one can write at all.
			if (!readerReady && browserReady) mode = 'browser';
		});
		return () => {
			writeAbort?.abort();
			opener?.focus();
		};
	});

	function close() {
		if (busy) return;
		writeAbort?.abort();
		onclose();
	}

	async function writeViaServer() {
		busy = true;
		result = null;
		try {
			// `success: false` here is an ordinary 200 carrying a reason -- no reader, no tag on
			// it, spool gone. Reporting only thrown errors would call every one of those a write.
			const res = await nfcWrite(spool.id, tagFormat, userMessage);
			result = { ok: res.success, message: res.message || ng.nfc_write_success() };
		} catch {
			result = { ok: false, message: ng.nfc_error_write_failed() };
		} finally {
			busy = false;
		}
	}

	async function writeViaBrowser() {
		busy = true;
		result = null;
		writeAbort?.abort();
		const controller = new AbortController();
		writeAbort = controller;
		try {
			const payload = encodeTigerTag(mapSpoolToTigerTag(spool, filament, userMessage));
			await writeTigerTagNdef(new Uint8Array(payload), controller.signal);
			result = { ok: true, message: ng.nfc_browser_write_success() };
		} catch (e) {
			// A cancelled write is the user closing the dialog, not a failure worth reporting.
			if (controller.signal.aborted) return;
			result = { ok: false, message: messageForNfcError(e) };
		} finally {
			busy = false;
		}
	}

	/** Web NFC reports through reason codes; the wording is this component's, as upstream's is. */
	function messageForNfcError(e: unknown): string {
		if (!(e instanceof NfcError)) return ng.nfc_error_write_failed();
		switch (e.reason) {
			case 'notAllowed':
				return ng.nfc_error_permission_denied();
			case 'unsupported':
			case 'insecureContext':
			case 'notSupported':
				return ng.nfc_error_not_supported();
			default:
				return ng.nfc_error_write_failed();
		}
	}

	/**
	 * Hand the raw bytes over as a file.
	 *
	 * Encoded server-side rather than with the local codec, though a cross-check against a
	 * running backend showed the two agree byte for byte (only the embedded timestamp differs,
	 * by the seconds between the two calls). The server stays the source because it is the one
	 * that owns the format: if the layout ever changes there, a downloaded file written by a
	 * stale client would be silently wrong, and this is the route whose entire purpose is a tag
	 * some other tool will read.
	 */
	async function downloadBinary() {
		busy = true;
		result = null;
		try {
			const res = await nfcEncode(spool.id, userMessage);
			if (!res.success) {
				result = { ok: false, message: res.message || ng.nfc_error_encode_failed() };
				return;
			}
			const bytes = Uint8Array.from(atob(res.binaryB64), (c) => c.charCodeAt(0));
			const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }));
			const a = document.createElement('a');
			a.href = url;
			a.download = `spool-${spool.id}-tigertag.bin`;
			a.click();
			// Revoked on the next frame rather than immediately: the click is asynchronous, and a
			// URL revoked in the same tick can be gone before the download starts.
			setTimeout(() => URL.revokeObjectURL(url), 0);
			toasts.success(ng.nfc_download_success());
		} catch {
			result = { ok: false, message: ng.nfc_error_encode_failed() };
		} finally {
			busy = false;
		}
	}

	const preview = $derived([
		{ label: ng.nfc_tag_material(), value: filament.material },
		{ label: ng.nfc_tag_color(), value: filament.colors[0] ?? '-' },
		{ label: ng.nfc_tag_diameter(), value: `${filament.diameter} mm` },
		{ label: ng.nfc_tag_weight(), value: `${filament.weight} g` },
		{ label: ng.nfc_tag_nozzle_temp(), value: `${filament.nozzleTemp} °C` },
		{ label: ng.nfc_tag_bed_temp(), value: `${filament.bedTemp} °C` }
	]);
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
		aria-labelledby="nfc-write-title"
		tabindex="-1"
		bind:this={dialog}
	>
		<div class="modal-head">
			<span class="title" id="nfc-write-title">{ng.nfc_encode_title()}</span>
			<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
		</div>

		<div class="body">
			<div class="modes" role="group" aria-label={ng.nfc_tag_format_label()}>
				<button
					class:active={mode === 'server'}
					disabled={readerReady === false}
					onclick={() => (mode = 'server')}>{ng.nfc_mode_server()}</button
				>
				<button class:active={mode === 'browser'} disabled={!browserReady} onclick={() => (mode = 'browser')}
					>{ng.nfc_mode_browser()}</button
				>
			</div>

			<!--
				Which of the two "you cannot write here" messages applies depends on which side is
				missing, and getting it wrong sends the user somewhere that also does not work.
				nfc.error.not_supported ends "Use the Server mode with a connected reader", so it
				is only honest when there IS one. With neither available -- the ordinary desktop
				case -- the reader is the thing to report, and the download below is what still
				works without any hardware at all.
			-->
			{#if readerReady === false && !browserReady}
				<p class="note">{ng.nfc_error_no_reader()}</p>
			{:else if readerReady && !browserReady}
				<p class="note">{ng.nfc_error_not_supported()}</p>
			{/if}

			{#if mode === 'server'}
				<label class="fld">
					<span class="lbl">{ng.nfc_tag_format()}</span>
					<div class="modes">
						<button class:active={tagFormat === 'tigertag'} onclick={() => (tagFormat = 'tigertag')}
							>TigerTag (NTAG213)</button
						>
						<button class:active={tagFormat === 'qidi'} onclick={() => (tagFormat = 'qidi')}
							>Qidi (MIFARE Classic)</button
						>
					</div>
				</label>
				{#if tagFormat === 'qidi'}
					<p class="note">{ng.nfc_qidi_write_info()}</p>
				{/if}
			{:else}
				<p class="note warn">{ng.nfc_browser_ndef_warning()}</p>
			{/if}

			{#if tagFormat === 'tigertag' || mode === 'browser'}
				<label class="fld">
					<span class="lbl">{ng.nfc_user_message()}</span>
					<input class="in" bind:value={userMessage} maxlength="28" disabled={busy} />
					<span class="hint">{ng.nfc_user_message_help()}</span>
				</label>
			{/if}

			<div class="preview">
				<span class="lbl">{ng.nfc_preview_title()}</span>
				<dl>
					{#each preview as row (row.label)}
						<div>
							<dt>{row.label}</dt>
							<dd>{row.value}</dd>
						</div>
					{/each}
				</dl>
			</div>

			{#if busy}
				<p class="note" role="status">{ng.nfc_writing()}</p>
			{/if}
			{#if result}
				<p class="note" class:err={!result.ok} class:ok={result.ok} role="alert">
					{result.message}
				</p>
			{/if}
		</div>

		<div class="foot">
			<Button variant="outline" disabled={busy} onclick={downloadBinary}>
				{ng.nfc_download_raw_binary()}
			</Button>
			<Button variant="outline" disabled={busy} onclick={close}>{m['buttons.cancel']()}</Button>
			<Button
				variant="primary"
				disabled={busy || (mode === 'server' ? readerReady === false : !browserReady)}
				onclick={mode === 'server' ? writeViaServer : writeViaBrowser}
			>
				{ng.nfc_encode_button()}
			</Button>
		</div>
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
		width: 480px;
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
		padding: 14px 20px 4px;
		overflow-y: auto;
	}
	.modes {
		display: flex;
		gap: 6px;
	}
	.modes button {
		flex: 1;
		padding: 6px 10px;
		font-size: 12.5px;
		color: var(--text-muted);
		background: var(--bg-subtle);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		cursor: pointer;
	}
	.modes button:hover:not(:disabled) {
		color: var(--text);
	}
	.modes button.active {
		color: var(--text);
		background: var(--bg-hover);
		border-color: var(--border-strong);
	}
	.modes button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
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
	.hint {
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.note {
		margin: 0;
		font-size: 12.5px;
		line-height: 1.5;
		color: var(--text-muted);
	}
	.note.warn {
		padding: 8px 10px;
		background: var(--bg-subtle);
		border-left: 2px solid var(--warning, var(--accent));
		border-radius: var(--radius-sm);
	}
	.note.err {
		color: var(--danger);
	}
	.note.ok {
		color: var(--success, var(--accent));
	}
	.preview dl {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 4px 12px;
		margin: 6px 0 0;
	}
	.preview dl div {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		font-size: 12.5px;
	}
	.preview dt {
		color: var(--text-muted);
	}
	.preview dd {
		margin: 0;
		color: var(--text);
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px 16px;
		flex: none;
	}
</style>
