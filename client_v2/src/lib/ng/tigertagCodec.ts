/**
 * TigerTag NTAG213 binary encoder/decoder for browser-side NFC.
 *
 * Ported byte-for-byte from `client/src/utils/tigertagCodec.ts` (the React client), which
 * implements the TigerTag Maker format (big-endian) per the TigerTag RFID Guide. `nfcApi.ts`
 * already lets this client ask the SERVER to encode and write a tag (`POST /nfc/write`,
 * `/nfc/encode`) through a reader attached back there; this module exists so a browser with its
 * own Web NFC support (Chrome on Android) can encode -- and eventually write -- a tag directly,
 * with no server round trip and no reader required on the backend at all.
 *
 * Produces/consumes 144-byte binary payloads for NTAG213 user memory (pages 4-39) -- the exact
 * bytes the physical TigerTag app reads off a real chip. A one-byte offset error here silently
 * corrupts a tag that looks fine until scanned elsewhere, so every offset below is copied, not
 * re-derived, from the React source, and cross-checked against the Python codec that writes the
 * same bytes server-side (`spoolman/tigertag_codec.py`). Where the two disagree, or where this
 * file preserves something that looks like a bug, it is called out at the point in question
 * rather than "fixed" -- see the discrepancy noted at `mapSpoolToTigerTag` below.
 *
 * `TigerTagBinaryData` deliberately keeps the wire's own snake_case field names (id_tigertag,
 * nozzle_temp, ...) instead of this client's usual camelCase. Like `SessionBody` in
 * calibrationTypes.ts, it names bytes on a physical chip and fields in the Python dataclass, not
 * a domain concept of this client's -- renaming it would only add a translation step, and one
 * more place an offset comment and a field name could quietly drift apart.
 */

import type { Filament, Spool } from '$lib/types';

/** TigerTag Maker v1.0 magic number (from id_version.json API -- the README hex values are incorrect). */
export const TIGERTAG_MAKER_V1 = 0x5bf59264;

/** TigerTag+ v1.0 magic number -- offline + cloud sync. */
export const TIGERTAG_PRO_V1 = 0xbc0fcb97;

/** Check if a magic number identifies a valid TigerTag (Maker or Pro/+). */
export function isTigerTag(magic: number): boolean {
	return magic === TIGERTAG_MAKER_V1 || magic === TIGERTAG_PRO_V1;
}

/** Seconds between Unix epoch (1970-01-01) and TigerTag epoch (2000-01-01). */
export const TIGERTAG_EPOCH_OFFSET = 946684800;

/** NTAG213 user memory size in bytes. */
const NTAG213_USER_BYTES = 144;

/** TigerTag Maker header size in bytes. */
const HEADER_SIZE = 36;

/** Maximum user message length in bytes. */
const USER_MESSAGE_SIZE = 28;

/** User message offset in the 144-byte payload. */
const USER_MESSAGE_OFFSET = 58;

const EMOJI_OFFSET = 54;

/** Bed temp offset (2 x uint8 after the 36-byte header). */
const BED_TEMP_OFFSET = 36;

/** TigerTag filament type ID. */
const TIGERTAG_TYPE_FILAMENT = 142;

export interface TigerTagBinaryData {
	id_tigertag: number;
	id_product: number;
	id_material: number;
	id_diameter: number;
	id_aspect: number;
	id_type: number;
	id_brand: number;
	color_r: number;
	color_g: number;
	color_b: number;
	color_a: number;
	weight: number;
	nozzle_temp: number;
	nozzle_temp_max: number;
	bed_temp: number;
	bed_temp_max: number;
	drying_temp: number;
	drying_duration: number;
	timestamp: number;
	emoji: number;
	user_message: string;
}

// TigerTag binary format (big-endian, 36-byte header):
//
// Offset  Size  Field
// 0       4     id_tigertag (uint32 BE)
// 4       4     id_product (uint32 BE)
// 8       2     id_material (uint16 BE)
// 10      1     id_aspect_1 (uint8)
// 11      1     id_aspect_2 (uint8)
// 12      1     id_type (uint8)
// 13      1     id_diameter (uint8)
// 14      2     id_brand (uint16 BE)
// 16      4     color_rgba (uint32 BE: R<<24 | G<<16 | B<<8 | A)
// 20      4     weight_unit (uint32 BE: weight<<8 | unit_id)
// 24      2     nozzle_temp_min (uint16 BE)
// 26      2     nozzle_temp_max (uint16 BE)
// 28      1     drying_temp (uint8)
// 29      1     drying_time (uint8, hours)
// 30      2     reserved (uint16)
// 32      4     timestamp (uint32 BE)
//
// After header:
// 36      1     bed_temp_min (uint8)
// 37      1     bed_temp_max (uint8)
// 38-53   16    reserved
// 54      4     emoji (uint32 BE)
// 58      28    user_message (UTF-8)
// 86-143  58    signature / reserved

/**
 * Decode a TigerTag binary payload into structured data.
 * Uses big-endian format as per the TigerTag RFID Guide specification.
 */
export function decodeTigerTag(buf: ArrayBuffer): TigerTagBinaryData {
	if (buf.byteLength < HEADER_SIZE) {
		throw new Error(`Data too short: expected at least ${HEADER_SIZE} bytes, got ${buf.byteLength}`);
	}

	const view = new DataView(buf);
	const BE = false; // DataView littleEndian=false -> big-endian

	let offset = 0;
	const id_tigertag = view.getUint32(offset, BE);
	offset += 4;
	const id_product = view.getUint32(offset, BE);
	offset += 4;
	const id_material = view.getUint16(offset, BE);
	offset += 2;
	const id_aspect = view.getUint8(offset);
	offset += 1; // aspect_1
	offset += 1; // aspect_2 -- present on the wire, but no field carries it; see encodeTigerTag.
	const id_type = view.getUint8(offset);
	offset += 1;
	const id_diameter = view.getUint8(offset);
	offset += 1;
	const id_brand = view.getUint16(offset, BE);
	offset += 2;

	// Color packed as uint32 BE: R<<24 | G<<16 | B<<8 | A
	const colorVal = view.getUint32(offset, BE);
	offset += 4;
	const color_r = (colorVal >>> 24) & 0xff;
	const color_g = (colorVal >>> 16) & 0xff;
	const color_b = (colorVal >>> 8) & 0xff;
	const color_a = colorVal & 0xff;

	// Weight + unit packed as uint32 BE: weight in upper 24 bits, unit in lower 8.
	// The unit id itself is discarded -- the whole format hardcodes unit=1 (grams) on encode
	// (see below) and nothing downstream reads anything else, so there is no field for it here.
	const weightUnit = view.getUint32(offset, BE);
	offset += 4;
	const weight = (weightUnit >>> 8) & 0xffffff;

	const nozzle_temp = view.getUint16(offset, BE);
	offset += 2;
	const nozzle_temp_max = view.getUint16(offset, BE);
	offset += 2;
	const drying_temp = view.getUint8(offset);
	offset += 1;
	const drying_duration = view.getUint8(offset);
	offset += 1;
	offset += 2; // reserved
	const timestamp = view.getUint32(offset, BE);
	offset += 4;

	// Bed temp at offset 36-37. Guarded separately from the 36-byte header check above because a
	// tag can legitimately be read back truncated (a partial NDEF read, a short mock in tests);
	// under-reading the header would be a real error, but a short tail should degrade to defaults
	// rather than throw.
	let bed_temp = 0;
	let bed_temp_max = 0;
	if (buf.byteLength > BED_TEMP_OFFSET + 1) {
		bed_temp = view.getUint8(BED_TEMP_OFFSET);
		bed_temp_max = view.getUint8(BED_TEMP_OFFSET + 1);
	}

	// Emoji at offset 54
	let emoji = 0;
	if (buf.byteLength >= EMOJI_OFFSET + 4) {
		emoji = view.getUint32(EMOJI_OFFSET, BE);
	}

	// User message at offset 58
	let user_message = '';
	if (buf.byteLength >= USER_MESSAGE_OFFSET + USER_MESSAGE_SIZE) {
		const msgSlice = new Uint8Array(buf, USER_MESSAGE_OFFSET, USER_MESSAGE_SIZE);
		const nullIdx = msgSlice.indexOf(0);
		const msgBytes = nullIdx >= 0 ? msgSlice.slice(0, nullIdx) : msgSlice;
		user_message = new TextDecoder().decode(msgBytes);
	}

	return {
		id_tigertag,
		id_product,
		id_material,
		id_diameter,
		id_aspect,
		id_type,
		id_brand,
		color_r,
		color_g,
		color_b,
		color_a,
		weight,
		nozzle_temp,
		nozzle_temp_max,
		bed_temp,
		bed_temp_max,
		drying_temp,
		drying_duration,
		timestamp,
		emoji,
		user_message
	};
}

/**
 * Encode TigerTag data into a 144-byte ArrayBuffer for NTAG213 user memory.
 * Uses big-endian format as per the TigerTag RFID Guide specification.
 */
export function encodeTigerTag(data: TigerTagBinaryData): ArrayBuffer {
	const buf = new ArrayBuffer(NTAG213_USER_BYTES);
	const view = new DataView(buf);
	const BE = false; // DataView littleEndian=false -> big-endian

	let offset = 0;

	// `>>> 0` forces an unsigned 32-bit read of a field the type calls `number` but a caller
	// could hand in negative or over-wide -- DataView.setUint32 would otherwise throw on a
	// value outside the uint32 range instead of wrapping the way the physical chip's bytes do.
	view.setUint32(offset, data.id_tigertag >>> 0, BE);
	offset += 4;
	view.setUint32(offset, data.id_product >>> 0, BE);
	offset += 4;
	view.setUint16(offset, data.id_material & 0xffff, BE);
	offset += 2;
	view.setUint8(offset, data.id_aspect & 0xff);
	offset += 1; // aspect_1
	view.setUint8(offset, 0);
	offset += 1; // aspect_2 -- always written as 0; there is no second aspect field to encode.
	view.setUint8(offset, data.id_type & 0xff);
	offset += 1;
	view.setUint8(offset, data.id_diameter & 0xff);
	offset += 1;
	view.setUint16(offset, data.id_brand & 0xffff, BE);
	offset += 2;

	// Color packed as uint32 BE: R<<24 | G<<16 | B<<8 | A. The shifts run in signed 32-bit
	// arithmetic, so a channel of 0x80 or above in the top byte position can produce a negative
	// intermediate value -- `>>> 0` below is load-bearing, not decorative, to get it back to the
	// unsigned value DataView expects.
	const colorVal =
		((data.color_r & 0xff) << 24) | ((data.color_g & 0xff) << 16) | ((data.color_b & 0xff) << 8) | (data.color_a & 0xff);
	view.setUint32(offset, colorVal >>> 0, BE);
	offset += 4;

	// Weight + unit BE: weight<<8 | unit (unit=1 for grams). `& 0xffffff` silently wraps a
	// weight at or above 16,777,216 g instead of clamping -- preserved from the React source
	// since no real spool will ever approach that, but it means this is not a saturating cast.
	const weightUnit = ((data.weight & 0xffffff) << 8) | 1;
	view.setUint32(offset, weightUnit >>> 0, BE);
	offset += 4;

	view.setUint16(offset, data.nozzle_temp & 0xffff, BE);
	offset += 2;
	view.setUint16(offset, (data.nozzle_temp_max || 0) & 0xffff, BE);
	offset += 2;
	// `& 0xff` wraps rather than clamps: a drying_temp/duration above 255 wraps modulo 256
	// instead of saturating at the max the chip can hold. Preserved as-is -- see module comment.
	view.setUint8(offset, data.drying_temp & 0xff);
	offset += 1;
	view.setUint8(offset, data.drying_duration & 0xff);
	offset += 1;
	view.setUint16(offset, 0, BE);
	offset += 2; // reserved
	view.setUint32(offset, data.timestamp >>> 0, BE);
	offset += 4;

	// Bed temp at offset 36-37
	view.setUint8(BED_TEMP_OFFSET, data.bed_temp & 0xff);
	view.setUint8(BED_TEMP_OFFSET + 1, (data.bed_temp_max || 0) & 0xff);

	// Emoji at offset 54
	view.setUint32(EMOJI_OFFSET, data.emoji >>> 0, BE);

	// User message at offset 58 (28 bytes, null-padded: the buffer starts zeroed and only the
	// bytes actually written are touched, so a short message leaves the rest as NUL).
	const encoder = new TextEncoder();
	const msgBytes = encoder.encode(data.user_message).slice(0, USER_MESSAGE_SIZE);
	const uint8 = new Uint8Array(buf);
	uint8.set(msgBytes, USER_MESSAGE_OFFSET);

	return buf;
}

/**
 * Map a Spool + its Filament to TigerTag binary data, mirroring the Python backend's
 * `map_spool_to_tigertag()`.
 *
 * Takes `filament` as a separate argument rather than reading `spool.filament` (the React
 * source's shape): in this client a `Spool` only carries `filamentId`, not the filament object
 * itself (see `types.ts`) -- callers already hold both from `Inventory.filamentById()`, so this
 * mirrors how the rest of `$lib/ng` and `$lib/stores` pass them around rather than inventing a
 * combined type just for this function.
 *
 * `filament.id` and `filament.vendorId` are never used below. This client's filament/vendor ids
 * are opaque strings (CockroachDB ids too large for a JS `number`), so there is nothing to parse
 * them into and no boundary cast to get wrong -- the one numeric id this function emits,
 * `id_product`, comes either from `spool.id` (still a plain integer serial in this client, see
 * `mapSpool` in `api/map.ts`) or from the numeric suffix of `filament.externalId`, which was a
 * string on both sides already.
 *
 * DISCREPANCY vs. the Python backend (report this, do not silently resolve it): the Python
 * `map_spool_to_tigertag` (spoolman/tigertag_lookup.py) accepts optional `brand_map` /
 * `material_map` dictionaries and, when given, looks up `id_brand` / `id_material` by matching
 * the vendor/material name. The React source this file ports (client/src/utils/tigertagCodec.ts)
 * takes no such maps and always leaves `id_brand` and `id_material` at 0. This port follows the
 * React source, per instructions, so `id_brand`/`id_material` are always 0 here too.
 */
export function mapSpoolToTigerTag(spool: Spool, filament: Filament, userMessage: string = ''): TigerTagBinaryData {
	const data: TigerTagBinaryData = {
		id_tigertag: TIGERTAG_MAKER_V1,
		id_product: 0,
		id_material: 0,
		id_diameter: 0,
		id_aspect: 0,
		id_type: TIGERTAG_TYPE_FILAMENT,
		id_brand: 0,
		color_r: 0,
		color_g: 0,
		color_b: 0,
		color_a: 255,
		weight: 0,
		nozzle_temp: 0,
		nozzle_temp_max: 0,
		bed_temp: 0,
		bed_temp_max: 0,
		drying_temp: 0,
		drying_duration: 0,
		timestamp: Math.floor(Date.now() / 1000) - TIGERTAG_EPOCH_OFFSET,
		emoji: 0,
		user_message: userMessage
	};

	// Set product ID: use TigerTag product ID if available, otherwise use spool ID
	if (filament.externalId?.startsWith('tigertag_')) {
		const parsed = parseInt(filament.externalId.split('_')[1], 10);
		data.id_product = !isNaN(parsed) ? parsed : spool.id;
	} else {
		data.id_product = spool.id;
	}

	if (filament.diameter) {
		if (Math.abs(filament.diameter - 1.75) < 0.1) {
			data.id_diameter = 1;
		} else if (Math.abs(filament.diameter - 2.85) < 0.1) {
			data.id_diameter = 2;
		}
	}

	// `colors[0]` is this client's equivalent of the React source's singular `color_hex`: a
	// multi-colour filament's other colours have nowhere to go in this format, same as upstream.
	const primaryColor = filament.colors[0];
	if (primaryColor) {
		const hex = primaryColor.replace(/^#/, '');
		if (hex.length >= 6) {
			data.color_r = parseInt(hex.substring(0, 2), 16);
			data.color_g = parseInt(hex.substring(2, 4), 16);
			data.color_b = parseInt(hex.substring(4, 6), 16);
			if (hex.length >= 8) {
				data.color_a = parseInt(hex.substring(6, 8), 16);
			}
		}
	}

	// Weight -- truncate to match the Python backend's map_spool_to_tigertag (int(filament.weight)),
	// so Web-NFC-written tags encode identically to backend-written ones for non-integer weights.
	if (filament.weight) {
		data.weight = Math.trunc(filament.weight);
	}

	// `nozzleTemp`/`bedTemp` default to 0 rather than being absent in this client's Filament
	// (see mapFilament in api/map.ts), unlike the React source's optional fields -- but 0 and
	// undefined are both falsy, so these guards skip an unset temp exactly as the source does.
	if (filament.nozzleTemp) {
		data.nozzle_temp = filament.nozzleTemp;
	}
	if (filament.bedTemp) {
		data.bed_temp = filament.bedTemp;
	}

	return data;
}
