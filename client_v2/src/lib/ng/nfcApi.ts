/**
 * Writing a spool's data ONTO an NFC tag -- the half of NFC upstream's client does not have.
 *
 * Upstream binds a tag by its hardware UID and never touches what is stored on it, so nothing
 * in `$lib/api` covers these endpoints. Kept out of ./api.ts because that module is about this
 * fork's own ENTITIES (orders, shops, locations) and this one is about a device: the two share
 * no types and are read by different people.
 *
 * All three endpoints answer 200 with `success: false` and a human-readable `message` rather
 * than raising, including for "NFC is not enabled on the server" and "no tag detected" -- so a
 * caller that only catches exceptions will report success on a tag that was never written. The
 * `success` flag is the result; an exception means the request itself failed.
 */
import { getJson, postJson } from '$lib/api/http';

/** Which binary layout to write. Qidi is server-only: MIFARE Classic is out of Web NFC's reach. */
export type TagFormat = 'tigertag' | 'qidi';

export interface NfcStatus {
	/** Whether the server was built and configured to talk to a reader at all. */
	enabled: boolean;
	/** 'connected' | 'disconnected' | 'disabled' | 'error', per the reader's own report. */
	status: string;
}

export interface NfcWriteResult {
	success: boolean;
	nfcTagUid?: string;
	message: string;
}

export interface NfcEncodeResult {
	success: boolean;
	/** Base64 of the 144-byte TigerTag payload. Empty when `success` is false. */
	binaryB64: string;
	message: string;
}

type Json = Record<string, unknown>;

/**
 * Whether a server-side reader is present, and what it says about itself.
 *
 * Reported rather than inferred: server writing is only offered when this says the reader is
 * there, and an unreachable status endpoint has to read as "no reader" instead of throwing the
 * whole modal away -- browser writing and the raw-binary download both still work without one.
 */
export async function nfcStatus(signal?: AbortSignal): Promise<NfcStatus> {
	try {
		const res = await getJson<Json>('/nfc/status', {}, signal);
		return { enabled: Boolean(res.enabled), status: String(res.status ?? 'error') };
	} catch {
		return { enabled: false, status: 'error' };
	}
}

/**
 * Write a spool onto the tag currently sitting on the server's reader.
 *
 * `userMessage` is a TigerTag-only field capped at 28 characters by the server, and is dropped
 * for Qidi rather than sent and ignored -- a Qidi tag stores material and colour and nothing
 * else, so sending a message there would suggest it was kept.
 */
export async function nfcWrite(
	spoolId: number,
	tagFormat: TagFormat,
	userMessage: string
): Promise<NfcWriteResult> {
	const body: Json = { spool_id: spoolId, tag_format: tagFormat };
	if (tagFormat === 'tigertag' && userMessage) body.user_message = userMessage;
	const res = await postJson<Json>('/nfc/write', body);
	return {
		success: Boolean(res.success),
		nfcTagUid: res.nfc_tag_uid == null ? undefined : String(res.nfc_tag_uid),
		message: String(res.message ?? '')
	};
}

/**
 * Produce the TigerTag binary for a spool without writing anything.
 *
 * No reader is involved, which is the point: this is the escape hatch for a desktop or iOS
 * user, whose browser has no Web NFC at all, to take the exact bytes to an external tool.
 */
export async function nfcEncode(spoolId: number, userMessage: string): Promise<NfcEncodeResult> {
	const res = await postJson<Json>('/nfc/encode', { spool_id: spoolId, user_message: userMessage });
	return {
		success: Boolean(res.success),
		binaryB64: String(res.binary_b64 ?? ''),
		message: String(res.message ?? '')
	};
}
