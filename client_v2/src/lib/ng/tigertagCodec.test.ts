import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Filament, Spool } from '$lib/types';
import {
	TIGERTAG_EPOCH_OFFSET,
	TIGERTAG_MAKER_V1,
	TIGERTAG_PRO_V1,
	decodeTigerTag,
	encodeTigerTag,
	isTigerTag,
	mapSpoolToTigerTag,
	type TigerTagBinaryData
} from './tigertagCodec';

// --- Fixtures ---------------------------------------------------------------

function filament(over: Partial<Filament> = {}): Filament {
	return {
		id: 'f1',
		vendorId: 'v1',
		name: 'PLA',
		material: 'PLA',
		colors: [],
		diameter: 1.75,
		density: 1.24,
		nozzleTemp: 0,
		bedTemp: 0,
		weight: 0,
		price: 0,
		comment: '',
		registeredLabel: 'Jan 1',
		extra: {},
		...over
	};
}

let nextId = 1;
function spool(over: Partial<Spool> = {}): Spool {
	return {
		id: nextId++,
		filamentId: 'f1',
		unused: true,
		remaining: 0,
		initial: 0,
		usedWeight: 0,
		location: '',
		lot: '',
		firstUsedLabel: '',
		lastUsedLabel: '',
		registeredLabel: 'Jan 1',
		archived: false,
		comment: '',
		tags: [],
		extra: {},
		...over
	};
}

const NTAG213_USER_BYTES = 144;

/**
 * Build a 144-byte TigerTag payload straight from the documented wire spec.
 *
 * This is the SAME golden vector used by the React test (client/src/utils/tigertagCodec.test.ts)
 * and the Python codec test (tests/nfc/test_tigertag_codec.py). It is hand-assembled byte-by-byte
 * (NOT produced by encodeTigerTag) so that asserting decodeTigerTag against it proves this port
 * agrees with both independent codecs on the wire format, not just with itself.
 */
function goldenPayload(): ArrayBuffer {
	const buf = new ArrayBuffer(NTAG213_USER_BYTES);
	const view = new DataView(buf);
	const BE = false; // DataView littleEndian=false -> big-endian

	view.setUint32(0, 0x5bf59264, BE); // id_tigertag = TigerTag Maker v1
	view.setUint32(4, 42, BE); // id_product   = 42
	view.setUint16(8, 7, BE); // id_material  = 7
	view.setUint8(10, 3); // aspect_1     = 3
	view.setUint8(11, 0); // aspect_2     = 0 (ignored by decoder)
	view.setUint8(12, 142); // id_type      = 142 (filament)
	view.setUint8(13, 1); // id_diameter  = 1 -> 1.75 mm
	view.setUint16(14, 5, BE); // id_brand     = 5
	view.setUint32(16, 0xff8800ff, BE); // color RGBA = #ff8800, alpha 255
	view.setUint32(20, 0x0003e801, BE); // weight_unit = (1000<<8)|1 -> 1000 g
	view.setUint16(24, 210, BE); // nozzle_min   = 210
	view.setUint16(26, 230, BE); // nozzle_max   = 230
	view.setUint8(28, 80); // drying_temp  = 80
	view.setUint8(29, 8); // drying_time  = 8 h
	view.setUint16(30, 0, BE); // reserved
	view.setUint32(32, 0x30000000, BE); // timestamp    = 0x30000000
	view.setUint8(36, 60); // bed_temp_min = 60
	view.setUint8(37, 70); // bed_temp_max = 70
	view.setUint32(54, 0x0001f600, BE); // emoji        = U+1F600

	const msg = new TextEncoder().encode('PLA Orange');
	new Uint8Array(buf).set(msg, 58); // user_message (null-padded to 28)

	return buf;
}

// --- Golden vector (cross-implementation equivalence) -----------------------

describe('decodeTigerTag - golden vector', () => {
	it('decodes every field to the value planted at its documented offset', () => {
		const data = decodeTigerTag(goldenPayload());

		expect(data.id_tigertag).toBe(TIGERTAG_MAKER_V1);
		expect(data.id_tigertag).toBe(0x5bf59264);
		expect(isTigerTag(data.id_tigertag)).toBe(true);
		expect(data.id_product).toBe(42);
		expect(data.id_material).toBe(7);
		expect(data.id_aspect).toBe(3);
		expect(data.id_type).toBe(142);
		expect(data.id_diameter).toBe(1);
		expect(data.id_brand).toBe(5);
		expect([data.color_r, data.color_g, data.color_b, data.color_a]).toEqual([255, 136, 0, 255]);
		expect(data.weight).toBe(1000);
		expect(data.nozzle_temp).toBe(210);
		expect(data.nozzle_temp_max).toBe(230);
		expect(data.drying_temp).toBe(80);
		expect(data.drying_duration).toBe(8);
		expect(data.timestamp).toBe(0x30000000);
		expect(data.bed_temp).toBe(60);
		expect(data.bed_temp_max).toBe(70);
		expect(data.emoji).toBe(0x0001f600);
		expect(data.user_message).toBe('PLA Orange');
	});
});

// --- Round-trip: encode and decode are independent, so agreement between them is a real oracle --

describe('encodeTigerTag / decodeTigerTag round-trip', () => {
	it('encode -> decode is loss-free for a hand-built struct within wire ranges', () => {
		const data: TigerTagBinaryData = {
			id_tigertag: TIGERTAG_MAKER_V1,
			id_product: 0x12345678,
			id_material: 0xabcd,
			id_diameter: 2,
			id_aspect: 3,
			id_type: 142,
			id_brand: 0x0102,
			color_r: 10,
			color_g: 20,
			color_b: 30,
			color_a: 200,
			weight: 750,
			nozzle_temp: 215,
			nozzle_temp_max: 225,
			bed_temp: 60,
			bed_temp_max: 65,
			drying_temp: 55,
			drying_duration: 6,
			timestamp: 0x30000000,
			emoji: 0x0001f600,
			user_message: 'Sunset Orange PLA'
		};

		const encoded = encodeTigerTag(data);
		expect(encoded.byteLength).toBe(NTAG213_USER_BYTES);

		const decoded = decodeTigerTag(encoded);
		expect(decoded).toEqual(data);
	});

	it('round-trips a TigerTag+ magic number and a max-range color channel', () => {
		// color_r = 0xff pushed into bit 24..31 goes negative in signed 32-bit arithmetic before
		// the `>>> 0` fixup in encodeTigerTag -- this pins that the fixup actually works.
		const data: TigerTagBinaryData = {
			id_tigertag: TIGERTAG_PRO_V1,
			id_product: 1,
			id_material: 0,
			id_diameter: 1,
			id_aspect: 0,
			id_type: 142,
			id_brand: 0,
			color_r: 255,
			color_g: 0,
			color_b: 0,
			color_a: 255,
			weight: 250,
			nozzle_temp: 200,
			nozzle_temp_max: 210,
			bed_temp: 50,
			bed_temp_max: 55,
			drying_temp: 45,
			drying_duration: 4,
			timestamp: 1,
			emoji: 0,
			user_message: ''
		};
		expect(decodeTigerTag(encodeTigerTag(data))).toEqual(data);
	});

	it('encodeTigerTag always emits exactly the NTAG213 user-memory size', () => {
		const minimal: TigerTagBinaryData = {
			id_tigertag: 0,
			id_product: 0,
			id_material: 0,
			id_diameter: 0,
			id_aspect: 0,
			id_type: 0,
			id_brand: 0,
			color_r: 0,
			color_g: 0,
			color_b: 0,
			color_a: 0,
			weight: 0,
			nozzle_temp: 0,
			nozzle_temp_max: 0,
			bed_temp: 0,
			bed_temp_max: 0,
			drying_temp: 0,
			drying_duration: 0,
			timestamp: 0,
			emoji: 0,
			user_message: ''
		};
		expect(encodeTigerTag(minimal).byteLength).toBe(144);
	});
});

// --- Defensive contract -------------------------------------------------------

describe('decodeTigerTag - short buffer', () => {
	it('throws on a buffer smaller than the 36-byte header', () => {
		expect(() => decodeTigerTag(new ArrayBuffer(35))).toThrow(/too short/);
	});
});

describe('encodeTigerTag - user_message truncation', () => {
	const base: TigerTagBinaryData = {
		id_tigertag: TIGERTAG_MAKER_V1,
		id_product: 1,
		id_material: 0,
		id_diameter: 1,
		id_aspect: 0,
		id_type: 142,
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
		timestamp: 0,
		emoji: 0,
		user_message: ''
	};

	it('truncates a message longer than the 28-byte field on encode -> decode', () => {
		const data = { ...base, user_message: 'x'.repeat(40) };
		const decoded = decodeTigerTag(encodeTigerTag(data));
		expect(decoded.user_message).toBe('x'.repeat(28));
	});

	it('round-trips an empty user_message back to an empty string, not a run of NUL chars', () => {
		// The whole 28-byte field is NUL, so the first NUL is at index 0. The decoder must treat
		// index 0 as "terminator at the start" (empty), not "no terminator found".
		expect(decodeTigerTag(encodeTigerTag(base)).user_message).toBe('');
	});

	it('does not write the user_message past its 28-byte field into the signature region', () => {
		// A 40-char message must be clamped on encode so bytes at/after offset 86 (the start of
		// the signature/reserved region) stay zero. Dropping the clamp would spill message bytes
		// into that region.
		const data = { ...base, user_message: 'x'.repeat(40) };
		const bytes = new Uint8Array(encodeTigerTag(data));
		expect(bytes[86]).toBe(0);
		expect(bytes[87]).toBe(0);
	});
});

// --- mapSpoolToTigerTag ------------------------------------------------------

describe('mapSpoolToTigerTag', () => {
	// 2024-01-01T00:00:00Z in Unix seconds is 1704067200. After subtracting the TigerTag epoch
	// offset this is a fixed, deterministic value.
	const fixedUnixMs = Date.UTC(2024, 0, 1, 0, 0, 0);

	beforeEach(() => {
		vi.useFakeTimers();
		vi.setSystemTime(new Date(fixedUnixMs));
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('uses a deterministic timestamp relative to the TigerTag epoch', () => {
		const data = mapSpoolToTigerTag(spool(), filament());
		const expected = Math.floor(fixedUnixMs / 1000) - TIGERTAG_EPOCH_OFFSET;
		expect(data.timestamp).toBe(expected);
	});

	it('always identifies as a filament TigerTag', () => {
		const data = mapSpoolToTigerTag(spool(), filament());
		expect(data.id_type).toBe(142);
		expect(data.id_tigertag).toBe(TIGERTAG_MAKER_V1);
	});

	it('derives id_product from a tigertag_ external_id', () => {
		const data = mapSpoolToTigerTag(spool(), filament({ externalId: 'tigertag_28' }));
		expect(data.id_product).toBe(28);
	});

	it('falls back to spool.id for a malformed external_id', () => {
		const data = mapSpoolToTigerTag(spool({ id: 999 }), filament({ externalId: 'tigertag_abc' }));
		expect(data.id_product).toBe(999);
	});

	it('falls back to spool.id when no external_id is present', () => {
		const data = mapSpoolToTigerTag(spool({ id: 777 }), filament());
		expect(data.id_product).toBe(777);
	});

	it('falls back to spool.id when the external_id is not a tigertag_ id', () => {
		// A non-tigertag external_id must NOT be parsed as a product id.
		const data = mapSpoolToTigerTag(spool({ id: 888 }), filament({ externalId: 'openprinttag_5' }));
		expect(data.id_product).toBe(888);
	});

	it('maps diameter 1.75 -> 1 and 2.85 -> 2', () => {
		expect(mapSpoolToTigerTag(spool(), filament({ diameter: 1.75 })).id_diameter).toBe(1);
		expect(mapSpoolToTigerTag(spool(), filament({ diameter: 2.85 })).id_diameter).toBe(2);
	});

	it('maps diameters within +/-0.1 of a known size, and 0 (unknown) just outside the tolerance', () => {
		// Inside the half-open tolerance window (|d - nominal| < 0.1) -> the coded size.
		expect(mapSpoolToTigerTag(spool(), filament({ diameter: 1.7 })).id_diameter).toBe(1);
		expect(mapSpoolToTigerTag(spool(), filament({ diameter: 2.9 })).id_diameter).toBe(2);
		// Exactly 0.1 away is OUTSIDE (strict <), and clearly-different diameters are unknown -> 0.
		expect(mapSpoolToTigerTag(spool(), filament({ diameter: 1.85 })).id_diameter).toBe(0);
		expect(mapSpoolToTigerTag(spool(), filament({ diameter: 2.95 })).id_diameter).toBe(0);
		expect(mapSpoolToTigerTag(spool(), filament({ diameter: 3.0 })).id_diameter).toBe(0);
	});

	it('parses the primary color into r/g/b channels, defaulting alpha to 255', () => {
		const data = mapSpoolToTigerTag(spool(), filament({ colors: ['#ff8800'] }));
		expect([data.color_r, data.color_g, data.color_b]).toEqual([255, 136, 0]);
		expect(data.color_a).toBe(255);
	});

	it('parses the alpha channel from an 8-digit color', () => {
		const data = mapSpoolToTigerTag(spool(), filament({ colors: ['#ff8800cc'] }));
		expect([data.color_r, data.color_g, data.color_b, data.color_a]).toEqual([255, 136, 0, 204]);
	});

	it('ignores a color too short to hold RGB, leaving the channels at their defaults', () => {
		const data = mapSpoolToTigerTag(spool(), filament({ colors: ['#fff'] }));
		expect([data.color_r, data.color_g, data.color_b]).toEqual([0, 0, 0]);
		expect(data.color_a).toBe(255);
	});

	it('leaves color at its default when the filament has no colors at all', () => {
		// A gradient/multi-color filament with an empty colors array (or a filament nobody has
		// colored yet) must not throw on colors[0] being undefined.
		const data = mapSpoolToTigerTag(spool(), filament({ colors: [] }));
		expect([data.color_r, data.color_g, data.color_b, data.color_a]).toEqual([0, 0, 0, 255]);
	});

	it('truncates filament weight to a whole gram, matching the Python backend int()', () => {
		const data = mapSpoolToTigerTag(spool(), filament({ weight: 999.6 }));
		expect(data.weight).toBe(999);
	});

	it('leaves weight at 0 (not NaN) when the filament has no weight', () => {
		// The guard must skip the truncate; entering it with weight 0 would still compute
		// Math.trunc(0) === 0, but this pins that the "no weight" path never reaches NaN for any
		// falsy input.
		expect(mapSpoolToTigerTag(spool(), filament()).weight).toBe(0);
	});

	it('copies extruder/bed temps when present and defaults them to 0 when absent', () => {
		const withTemps = mapSpoolToTigerTag(spool(), filament({ nozzleTemp: 215, bedTemp: 60 }));
		expect(withTemps.nozzle_temp).toBe(215);
		expect(withTemps.bed_temp).toBe(60);

		const withoutTemps = mapSpoolToTigerTag(spool(), filament());
		expect(withoutTemps.nozzle_temp).toBe(0);
		expect(withoutTemps.bed_temp).toBe(0);
	});

	it('defaults user_message to an empty string, and uses the argument when given', () => {
		// No message argument -> the default "" (not some other sentinel).
		expect(mapSpoolToTigerTag(spool(), filament()).user_message).toBe('');
		// Explicit message is carried through unchanged.
		expect(mapSpoolToTigerTag(spool(), filament(), 'Shelf B').user_message).toBe('Shelf B');
	});

	it('maps a realistic Spool + Filament end to end', () => {
		const f = filament({
			id: 'f-42',
			vendorId: 'v-7',
			name: 'Galaxy Black PLA',
			diameter: 1.75,
			weight: 1000.4,
			colors: ['#1a1a2e'],
			nozzleTemp: 210,
			bedTemp: 55,
			externalId: 'tigertag_555'
		});
		const s = spool({ id: 12, filamentId: 'f-42' });

		const data = mapSpoolToTigerTag(s, f, 'Bin 3');

		expect(data.id_product).toBe(555); // from filament.externalId, not spool.id
		expect(data.id_diameter).toBe(1);
		expect([data.color_r, data.color_g, data.color_b, data.color_a]).toEqual([0x1a, 0x1a, 0x2e, 255]);
		expect(data.weight).toBe(1000);
		expect(data.nozzle_temp).toBe(210);
		expect(data.bed_temp).toBe(55);
		expect(data.user_message).toBe('Bin 3');
		expect(data.id_type).toBe(142);

		// The mapping must itself be a valid, round-trippable TigerTag payload.
		expect(decodeTigerTag(encodeTigerTag(data))).toEqual(data);
	});
});

describe('isTigerTag', () => {
	it('recognises BOTH the Maker and the Pro/+ magic numbers', () => {
		// Both magics must be accepted -- dropping either half of the check is a bug.
		expect(isTigerTag(TIGERTAG_MAKER_V1)).toBe(true);
		expect(isTigerTag(TIGERTAG_PRO_V1)).toBe(true);
	});

	it('returns false for magic numbers that are not a TigerTag', () => {
		expect(isTigerTag(0x12345678)).toBe(false);
		expect(isTigerTag(0)).toBe(false);
	});
});

describe('decodeTigerTag with truncated-but-valid buffers', () => {
	it('decodes a header-only (36-byte) buffer, defaulting the trailing fields', () => {
		const data = decodeTigerTag(goldenPayload().slice(0, 36));
		// Header fields still decode correctly.
		expect(data.id_tigertag).toBe(TIGERTAG_MAKER_V1);
		expect(data.weight).toBe(1000);
		// Fields past the header are absent, so they take their defaults (no over-read).
		expect(data.bed_temp).toBe(0);
		expect(data.bed_temp_max).toBe(0);
		expect(data.emoji).toBe(0);
		expect(data.user_message).toBe('');
	});

	it('does not read a partial bed-temp pair: a 37-byte buffer keeps them at 0 without over-reading', () => {
		// 37 bytes means offset 37 (bed_temp_max) is out of range. The guard must exclude this
		// case; reading it anyway would throw a RangeError on the DataView.
		const data = decodeTigerTag(goldenPayload().slice(0, 37));
		expect(data.bed_temp).toBe(0);
		expect(data.bed_temp_max).toBe(0);
	});

	it('reads the bed temps once the buffer includes them (38 bytes), still defaulting emoji/message', () => {
		const data = decodeTigerTag(goldenPayload().slice(0, 38));
		expect(data.bed_temp).toBe(60);
		expect(data.bed_temp_max).toBe(70);
		expect(data.emoji).toBe(0);
		expect(data.user_message).toBe('');
	});

	it('does not partially read the emoji: a 56-byte buffer keeps it at 0 without over-reading', () => {
		// 56 bytes is past the bed temps but short of the 4-byte emoji at offset 54..57. The
		// guard must exclude it; a mis-sized guard would read out of range and throw.
		const data = decodeTigerTag(goldenPayload().slice(0, 56));
		expect(data.emoji).toBe(0);
		expect(data.user_message).toBe('');
	});

	it('reads the emoji once the buffer includes it (58 bytes), still defaulting the message', () => {
		const data = decodeTigerTag(goldenPayload().slice(0, 58));
		expect(data.emoji).toBe(0x0001f600);
		expect(data.user_message).toBe('');
	});

	it('reads the user message once the buffer includes it (86 bytes)', () => {
		const data = decodeTigerTag(goldenPayload().slice(0, 86));
		expect(data.user_message).toBe('PLA Orange');
	});
});
