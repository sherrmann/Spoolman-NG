import QRCode from 'qrcode';
import type { QrElement, LabelKind } from './types';

// QR content + geometry. The QR encodes a link back to the label's subject — a
// spool for spool labels, a filament for filament labels. The first two forms are
// understood by Spoolman's scanner ($lib/utils/spoolCode.ts):
//   scheme → WEB+SPOOLMAN:S-<id> / F-<id> / L-<id>     (compact custom URI)
//   url    → <base_url>/{spool,filament,location}/show/<id>     (opens in a browser)
//   custom → the element's urlTemplate                 (user-supplied, {id} substituted)
// A custom target is meant for a third-party app or host and won't scan back
// into Spoolman.

export interface QrContext {
	baseUrl: string;
	/** Whether the {id} refers to a spool, a filament or a location. Defaults to `spool`. */
	kind?: LabelKind;
}

/** Build the string encoded in a QR element for a given subject id. */
export function qrContent(el: QrElement, id: number | string, ctx: QrContext): string {
	return qrTemplate(el, ctx).replace('{id}', String(id));
}

/**
 * The same string as {@link qrContent}, but with a literal `{id}` where the
 * subject id goes — used for the encoding preview in the element inspector.
 */
export function qrTemplate(el: QrElement, ctx: QrContext): string {
	if (el.encoding === 'custom') {
		return el.urlTemplate ?? '';
	}
	if (el.encoding === 'url') {
		return `${webRoot(ctx)}/${showPath(ctx)}/show/{id}`;
	}
	return `WEB+SPOOLMAN:${schemePrefix(ctx)}-{id}`;
}

/** The URL that the `url` encoding would produce, with a literal `{id}`. Used as
 * the starting point when the user switches an element to a custom template. */
export function defaultUrlTemplate(ctx: QrContext): string {
	return `${webRoot(ctx)}/${showPath(ctx)}/show/{id}`;
}

function webRoot(ctx: QrContext): string {
	const root = ctx.baseUrl || (typeof window !== 'undefined' ? window.location.origin : '');
	return root.replace(/\/$/, '');
}
// Both helpers are switches rather than the two-way tests they replace: LabelKind has
// three members now, and `kind === 'filament' ? x : y` quietly hands a location label the
// spool answer -- a location QR that opens some unrelated spool. See
// docs/upstream/client-v2-fork-additions.md.

/** Route segment for the browser link. */
function showPath(ctx: QrContext): 'spool' | 'filament' | 'location' {
	switch (ctx.kind) {
		case 'filament':
			return 'filament';
		case 'location':
			return 'location';
		default:
			return 'spool';
	}
}
/**
 * Compact-scheme entity prefix: `S` for spools, `F` for filaments, `L` for locations.
 *
 * `L` is not a new invention -- it is the scheme this fork's React client has printed on
 * location labels since #84 (client/src/pages/printing/locationQrCodePrintingDialog.tsx
 * encodes `WEB+SPOOLMAN:L-<id>`), and `/location/show/<id>` is the URL form it pairs with.
 * Matching both exactly is what lets a label printed by either client scan into the other.
 */
function schemePrefix(ctx: QrContext): 'S' | 'F' | 'L' {
	switch (ctx.kind) {
		case 'filament':
			return 'F';
		case 'location':
			return 'L';
		default:
			return 'S';
	}
}

/** A square boolean module grid for the given text. */
export function qrModules(
	text: string,
	ec: QrElement['ec']
): { count: number; dark: (r: number, c: number) => boolean } {
	const qr = QRCode.create(text || ' ', { errorCorrectionLevel: ec });
	const count = qr.modules.size;
	const data = qr.modules.data;
	return {
		count,
		dark: (r, c) => data[r * count + c] === 1
	};
}

/**
 * SVG path `data` (in mm) for the dark modules of a QR code that fits in a
 * `sizeMm × sizeMm` box. Rendered as a single Konva.Path so it stays crisp at
 * any export DPI. Returns an empty string if the text can't be encoded.
 */
export function qrPathData(text: string, ec: QrElement['ec'], sizeMm: number): string {
	let grid: { count: number; dark: (r: number, c: number) => boolean };
	try {
		grid = qrModules(text, ec);
	} catch {
		return '';
	}
	const m = sizeMm / grid.count;
	let d = '';
	for (let r = 0; r < grid.count; r++) {
		for (let c = 0; c < grid.count; c++) {
			if (grid.dark(r, c)) {
				const x = c * m;
				const y = r * m;
				d += `M${x} ${y}h${m}v${m}h${-m}z`;
			}
		}
	}
	return d;
}
