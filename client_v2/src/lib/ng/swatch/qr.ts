// Ported from the classic client's client/src/utils/swatch/qr.ts (#415 step 3).
// Adapted for client_v2: rewritten on the `qrcode` package (already a client_v2
// dependency, used by $lib/labels/qr.ts) instead of `qrcode-generator`, which
// client_v2 does not depend on. The chosen mode is passed explicitly as a
// segment so the encoder does not have to re-derive it.
import QRCode from 'qrcode';
import type { QRCodeSegment } from 'qrcode';

export type QrEcLevel = 'L' | 'M' | 'Q' | 'H';
export type QrMode = 'Numeric' | 'Alphanumeric' | 'Byte';

const NUMERIC = /^[0-9]+$/;
/** The QR alphanumeric charset (ISO/IEC 18004): digits, upper-case letters and " $%*+-./:". */
const ALPHANUMERIC = /^[0-9A-Z $%*+\-./:]+$/;

/**
 * The densest QR encoding mode that can represent the payload. The default
 * `WEB+SPOOLMAN:F-<id>` payloads are all-uppercase on purpose: alphanumeric
 * mode packs them into a QR one version smaller than byte mode (21 instead of
 * 25 modules), which prints larger, cleaner modules in the same area.
 */
export function pickQrMode(payload: string): QrMode {
	if (NUMERIC.test(payload)) return 'Numeric';
	if (ALPHANUMERIC.test(payload)) return 'Alphanumeric';
	return 'Byte';
}

/** Map a QrMode to the segment mode name the `qrcode` package expects. */
function segmentMode(mode: QrMode): 'numeric' | 'alphanumeric' | 'byte' {
	switch (mode) {
		case 'Numeric':
			return 'numeric';
		case 'Alphanumeric':
			return 'alphanumeric';
		case 'Byte':
			return 'byte';
	}
}

/**
 * Encode a payload as a QR symbol and return its module matrix
 * (row-major, true = dark module). The smallest version that fits is used.
 */
export function makeQrModules(payload: string, ecLevel: QrEcLevel = 'M'): boolean[][] {
	const mode = segmentMode(pickQrMode(payload));
	const qr = QRCode.create([{ data: payload, mode } as QRCodeSegment], { errorCorrectionLevel: ecLevel });
	const count = qr.modules.size;
	const data = qr.modules.data;
	const modules: boolean[][] = [];
	for (let row = 0; row < count; row++) {
		const cells: boolean[] = [];
		for (let col = 0; col < count; col++) {
			cells.push(data[row * count + col] === 1);
		}
		modules.push(cells);
	}
	return modules;
}
