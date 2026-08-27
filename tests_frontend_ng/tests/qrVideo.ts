// Synthesise a Y4M video of QR codes, so the scanner can be driven end to end.
//
// Chromium's --use-file-for-fake-video-capture replaces the camera with a Y4M file and loops it,
// which is the only way to exercise a decode: the scanner reads frames off a <video>, so there is
// no seam to inject a payload at without reaching inside the vendored component. Y4M is written
// here rather than shelled out to ffmpeg because the container has neither ffmpeg nor ImageMagick,
// and the format is small enough not to need them -- an ASCII header, then one uncompressed
// planar YUV420 frame per `FRAME\n`.
//
// Encoding is deliberately crude and that is the point: a QR module is either black or white, so
// Y is 0 or 255 and the chroma planes are a flat 128. Nothing here has to look like a photograph;
// it has to decode.
import QRCode from 'qrcode';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const WIDTH = 640;
const HEIGHT = 480;
/** Frames each payload is held for. The scanner reads 5/s, so this is ~2s of a steady label. */
const FRAMES_PER_PAYLOAD = 20;

/** The luma plane for one payload: a centred, quiet-zoned QR on white. */
function lumaFor(payload: string): Buffer {
	const { modules } = QRCode.create(payload, { errorCorrectionLevel: 'M' });
	const size = modules.size;
	// Half the short side, and the fraction is the whole reason this works: qr-scanner only
	// looks at a centred square of 2/3 the frame, so a code drawn any larger is cropped by the
	// scan region and never decodes -- measured, after a first attempt at 0.75 produced a
	// picture-perfect QR the scanner stared straight through. Half leaves a quiet zone inside
	// that region on every side.
	//
	// Whole pixels, not a fractional scale: a module edge landing mid-pixel blurs, and a blurred
	// edge is what a decoder gives up on.
	const scale = Math.floor((Math.min(WIDTH, HEIGHT) * 0.5) / size);
	const drawn = size * scale;
	const x0 = Math.floor((WIDTH - drawn) / 2);
	const y0 = Math.floor((HEIGHT - drawn) / 2);

	const y = Buffer.alloc(WIDTH * HEIGHT, 255);
	for (let row = 0; row < drawn; row++) {
		for (let col = 0; col < drawn; col++) {
			const dark = modules.data[Math.floor(row / scale) * size + Math.floor(col / scale)];
			if (dark) y[(y0 + row) * WIDTH + (x0 + col)] = 0;
		}
	}
	return y;
}

/**
 * Write a looping Y4M holding each payload in turn, and return its path.
 *
 * Several payloads make the two-scan move flow testable: Chromium loops the file, so a spool
 * label followed by a location label is what the state machine sees, in that order, repeatedly.
 * Re-scanning is not a hazard -- the machine treats the held spool coming back into view as
 * nothing to report, which is exactly the real-world case this mirrors.
 */
export function writeQrVideo(payloads: string[]): string {
	const chroma = Buffer.alloc((WIDTH / 2) * (HEIGHT / 2), 128);
	const parts: Buffer[] = [Buffer.from(`YUV4MPEG2 W${WIDTH} H${HEIGHT} F10:1 Ip A1:1 C420\n`)];
	for (const payload of payloads) {
		const y = lumaFor(payload);
		for (let f = 0; f < FRAMES_PER_PAYLOAD; f++) {
			parts.push(Buffer.from('FRAME\n'), y, chroma, chroma);
		}
	}
	const path = join(mkdtempSync(join(tmpdir(), 'qrvid-')), 'camera.y4m');
	writeFileSync(path, Buffer.concat(parts));
	return path;
}
