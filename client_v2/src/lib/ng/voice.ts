/**
 * Recording a voice clip in the browser and getting text back.
 *
 * Split from the drawer because everything here is browser API and error mapping, and none of
 * it is about chat: it can be read, and reasoned about, without the conversation around it.
 *
 * Push-to-talk rather than a start/stop toggle, matching the React client. A toggle leaves the
 * microphone live if the user walks away from a half-finished thought; holding a button cannot.
 * That makes release, cancel and unmount all the same operation, which is why `stop()` is safe
 * to call more than once and from any of them.
 */

/** Why recording failed, in terms a message can be written for. */
export type VoiceErrorReason =
	/** No MediaRecorder or no getUserMedia -- an old browser, or an insecure origin. */
	| 'unsupported'
	/** The user declined the microphone prompt, or it is blocked for this site. */
	| 'notAllowed'
	/** No microphone present, or it is held by another application. */
	| 'unavailable'
	/** The clip reached the server but transcription failed. */
	| 'transcription'
	| 'unknown';

export class VoiceError extends Error {
	constructor(readonly reason: VoiceErrorReason) {
		super(`Voice capture failed: ${reason}`);
		this.name = 'VoiceError';
	}
}

/**
 * Whether this browser can record at all.
 *
 * Checked before the control is rendered, not after it is pressed: the same rule
 * $lib/utils/nfc states for tag reading, and for the same reason -- a dead button the user
 * cannot explain is worse than no button.
 */
export function voiceSupported(): boolean {
	if (typeof window === 'undefined') return false;
	return (
		typeof window.MediaRecorder !== 'undefined' &&
		typeof navigator !== 'undefined' &&
		!!navigator.mediaDevices?.getUserMedia &&
		window.isSecureContext
	);
}

/**
 * The recording container to ask for.
 *
 * Ordered by what the speech-to-text endpoints actually accept. `isTypeSupported` is consulted
 * rather than assumed because the answer differs by browser and by platform -- Chrome on
 * Android and desktop Safari do not agree -- and passing an unsupported type to MediaRecorder
 * throws rather than falling back.
 */
const PREFERRED_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'];

function pickMimeType(): string | undefined {
	if (typeof window.MediaRecorder?.isTypeSupported !== 'function') return undefined;
	return PREFERRED_TYPES.find((t) => window.MediaRecorder.isTypeSupported(t));
}

function reasonFor(err: unknown): VoiceErrorReason {
	const name = (err as { name?: string } | null)?.name ?? '';
	if (name === 'NotAllowedError' || name === 'SecurityError') return 'notAllowed';
	if (name === 'NotFoundError' || name === 'NotReadableError' || name === 'OverconstrainedError')
		return 'unavailable';
	return 'unknown';
}

export interface Recording {
	/** Stop, release the microphone, and resolve with what was captured. Safe to call twice. */
	stop(): Promise<Blob>;
	/** Stop and release WITHOUT resolving a clip -- for a cancelled press or an unmount. */
	cancel(): void;
	/** The container actually recorded, for the upload's filename and content type. */
	mimeType: string;
}

/**
 * Start recording, or throw a `VoiceError` naming why not.
 *
 * The returned handle owns the microphone until `stop` or `cancel`. Every exit path stops the
 * tracks: a live track keeps the browser's recording indicator on, which is alarming and is the
 * user's evidence that something is listening when nothing should be.
 */
export async function startRecording(): Promise<Recording> {
	if (!voiceSupported()) throw new VoiceError('unsupported');

	let stream: MediaStream;
	try {
		stream = await navigator.mediaDevices.getUserMedia({ audio: true });
	} catch (err) {
		throw new VoiceError(reasonFor(err));
	}

	const release = () => stream.getTracks().forEach((t) => t.stop());

	const mimeType = pickMimeType();
	let recorder: MediaRecorder;
	try {
		recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
	} catch (err) {
		release();
		throw new VoiceError(reasonFor(err));
	}

	const chunks: Blob[] = [];
	recorder.addEventListener('dataavailable', (e) => {
		if (e.data.size > 0) chunks.push(e.data);
	});
	recorder.start();

	let settled: Promise<Blob> | null = null;
	return {
		mimeType: recorder.mimeType || mimeType || 'audio/webm',
		stop() {
			// Memoised so a release handler and a keyup handler firing together get the same
			// clip rather than the second one resolving empty.
			settled ??= new Promise<Blob>((resolve) => {
				const finish = () => {
					release();
					resolve(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }));
				};
				if (recorder.state === 'inactive') finish();
				else recorder.addEventListener('stop', finish, { once: true });
				if (recorder.state !== 'inactive') recorder.stop();
			});
			return settled;
		},
		cancel() {
			if (recorder.state !== 'inactive') recorder.stop();
			release();
		}
	};
}

/**
 * How long a clip may run before it is cut off, in milliseconds.
 *
 * The server rejects an oversized upload with a 413, which arrives only after the whole thing
 * has been recorded and sent. Stopping first turns "your clip was refused" into a clip that
 * simply ends, which is the better failure for something the user is holding a button through.
 */
export const MAX_CLIP_MS = 60_000;
