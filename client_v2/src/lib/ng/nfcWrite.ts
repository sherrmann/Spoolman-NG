/**
 * Writing an NDEF record with the phone you are holding.
 *
 * `$lib/utils/nfc` covers the read side and stops at the UID, because that is all upstream's
 * tag linking needs -- its `NDEFReaderLike` has no `write` at all. Rather than widen that
 * interface (a vendored file, and a conflict on every pull), the write half is declared here
 * and everything that can be shared is imported from it: `nfcSupported` and `NfcError` decide
 * whether to offer the control and how a failure is worded, and those answers must not differ
 * between reading and writing.
 *
 * What this produces is deliberately NOT what a TigerTag reader expects. The TigerTag app
 * reads raw bytes out of NTAG213 pages 4-39; Web NFC can only write NDEF, which wraps those
 * bytes in a record structure and puts them elsewhere. So the payload is identical and the
 * tag is still not recognised -- the caller must say so before the user writes, which is what
 * nfc.browser_ndef_warning is for.
 */
import { NfcError, nfcSupported } from '$lib/utils/nfc';

/** The external record type TigerTag's own writers use. Kept byte-identical to the React client. */
const TIGERTAG_RECORD_TYPE = 'tigertag.io:maker';

interface NDEFWriterLike {
	// `ArrayBufferLike` rather than the DOM's `BufferSource`: since TypeScript 5.7 a plain
	// `Uint8Array` is `Uint8Array<ArrayBufferLike>`, which the DOM type (fixed to `ArrayBuffer`)
	// rejects because it could in principle be backed by a SharedArrayBuffer. Nothing here ever
	// produces one, and widening our own declaration is honest -- the runtime accepts any typed
	// array -- where a cast at the call site would only hide the question.
	write(message: {
		records: { recordType: string; data: ArrayBufferView<ArrayBufferLike> }[];
	}): Promise<void>;
}

type NDEFReaderCtor = new () => NDEFWriterLike;

function reasonFor(err: unknown) {
	const name = (err as { name?: string } | null)?.name ?? '';
	if (name === 'NotAllowedError' || name === 'SecurityError') return 'notAllowed' as const;
	if (name === 'NotSupportedError') return 'notSupported' as const;
	if (name === 'NotReadableError') return 'notReadable' as const;
	return 'unknown' as const;
}

/**
 * Write one TigerTag payload to whatever tag is tapped next.
 *
 * Resolves when the tag has been written. Rejects with an `NfcError` carrying a reason, or
 * with the abort's reason when cancelled -- so callers must check `signal.aborted` before
 * reporting anything, exactly as `readTagUid` requires. The radio stays live until a tag
 * arrives, so a dialog that closes without aborting leaves it running behind a screen nobody
 * is looking at.
 */
export async function writeTigerTagNdef(payload: Uint8Array, signal: AbortSignal): Promise<void> {
	if (!nfcSupported()) {
		throw new NfcError(
			typeof window !== 'undefined' && !window.isSecureContext ? 'insecureContext' : 'unsupported'
		);
	}
	if (signal.aborted) throw signal.reason;

	const Ctor = (window as unknown as { NDEFReader: NDEFReaderCtor }).NDEFReader;
	let writer: NDEFWriterLike;
	try {
		writer = new Ctor();
	} catch (err) {
		throw new NfcError(reasonFor(err));
	}

	try {
		await writer.write({ records: [{ recordType: TIGERTAG_RECORD_TYPE, data: payload }] });
	} catch (err) {
		// A cancelled write is the caller closing the dialog, not a failure to report.
		if (signal.aborted) throw signal.reason;
		throw new NfcError(reasonFor(err));
	}
}
