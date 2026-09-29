// Ported from the classic client's client/src/utils/threeMfImport.test.ts (#414 step 2).
// Adapted for client_v2: the production code calls the browser's DOMParser directly, and
// client_v2's vitest runs in a plain node environment with no jsdom/DOMParser dependency. This
// stubs a global DOMParser built on the local strict XML test parser (see xmlTestHelpers.ts),
// shaped so a malformed document reports a `parsererror` element the way a real DOMParser would
// (it never throws). It also swaps the Svelte view model in for the classic ISpool/IFilament
// shapes: a spool links to its filament by `filamentId`, and a filament's colours live in
// `colors` (first entry is primary), so `spoolPrimaryHex`/`autoMatchSpoolId` take the filament
// list alongside the spools. Errors are asserted by their `code`, not by English message text.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { strToU8, zipSync } from 'fflate';
import type { Spool } from '$lib/types';
import type { ForkFilament } from '$lib/ng/types';
import {
	autoMatchSpoolId,
	normalizeHex,
	parseSliceInfo,
	parseThreeMf,
	spoolPrimaryHex,
	ThreeMfError
} from './threeMfImport';
import { parseXml, XmlParseError } from './swatch/xmlTestHelpers';

const SLICE_INFO = `<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="index" value="1"/>
    <filament id="1" type="PLA" color="#FF0000FF" used_m="3.45" used_g="10.5"/>
    <filament id="2" type="PETG" color="#00FF00" used_m="1.00" used_g="4.0"/>
  </plate>
  <plate>
    <metadata key="index" value="2"/>
    <filament id="1" type="PLA" color="#FF0000FF" used_m="1.00" used_g="2.5"/>
  </plate>
</config>`;

/**
 * A DOMParser shim on top of the strict test XML parser. A real DOMParser never throws on
 * malformed input; it returns a document whose `getElementsByTagName('parsererror')` is
 * non-empty. `parseXml` throws instead, so this catches that and reshapes it to match.
 */
class FakeDOMParser {
	parseFromString(xml: string) {
		try {
			return parseXml(xml);
		} catch (error) {
			if (!(error instanceof XmlParseError)) throw error;
			return {
				getElementsByTagName: (name: string) => (name === 'parsererror' ? [{}] : [])
			};
		}
	}
}

beforeEach(() => vi.stubGlobal('DOMParser', FakeDOMParser));
afterEach(() => vi.unstubAllGlobals());

function filament(id: string, over: Partial<ForkFilament> = {}): ForkFilament {
	return {
		id,
		vendorId: 'v1',
		name: 'Test filament',
		material: 'PLA',
		colors: ['#FF0000'],
		diameter: 1.75,
		density: 1.24,
		nozzleTemp: 200,
		bedTemp: 60,
		weight: 1000,
		price: 20,
		comment: '',
		...over
	} as unknown as ForkFilament;
}

function spool(id: number, filamentId: string, over: Partial<Spool> = {}): Spool {
	return {
		id,
		filamentId,
		unused: false,
		remaining: 1000,
		initial: 1000,
		usedWeight: 0,
		location: '',
		lot: '',
		...over
	} as unknown as Spool;
}

describe('normalizeHex', () => {
	it('strips the alpha and upper-cases', () => {
		expect(normalizeHex('#ff0000ff')).toBe('#FF0000');
		expect(normalizeHex('00ff00')).toBe('#00FF00');
	});
	it('returns undefined for empty or too-short values', () => {
		expect(normalizeHex(null)).toBeUndefined();
		expect(normalizeHex('#abc')).toBeUndefined();
	});
});

describe('parseSliceInfo', () => {
	it("sums a filament's usage across plates and keeps type/colour", () => {
		const result = parseSliceInfo(SLICE_INFO);
		expect(result).toEqual([
			{ key: '1', type: 'PLA', colorHex: '#FF0000', usedWeight: 13 },
			{ key: '2', type: 'PETG', colorHex: '#00FF00', usedWeight: 4 }
		]);
	});

	it('drops filaments that consumed nothing', () => {
		const xml = '<config><plate><filament id="1" type="PLA" color="#000000" used_g="0"/></plate></config>';
		expect(parseSliceInfo(xml)).toEqual([]);
	});

	it('throws an invalid_file ThreeMfError on malformed XML', () => {
		expect(() => parseSliceInfo('<config><plate>')).toThrow(ThreeMfError);
		expect(() => parseSliceInfo('<config><plate>')).toThrowError(
			expect.objectContaining({ code: 'invalid_file' })
		);
	});

	it('leaves out a filament with no colour attribute, and still counts it', () => {
		const xml = '<config><plate><filament id="1" type="PLA" used_g="5"/></plate></config>';
		expect(parseSliceInfo(xml)).toEqual([{ key: '1', type: 'PLA', colorHex: undefined, usedWeight: 5 }]);
	});

	it('gives a filament with no id attribute a key, and still counts it', () => {
		const xml = '<config><plate><filament type="PLA" color="#FF0000" used_g="5"/></plate></config>';
		const result = parseSliceInfo(xml);
		expect(result).toHaveLength(1);
		expect(result[0].key).toBe('noid-1');
		expect(result[0].usedWeight).toBe(5);
	});
});

describe('parseThreeMf', () => {
	it('unzips a 3mf and reads its slice_info.config', () => {
		const bytes = zipSync({ 'Metadata/slice_info.config': strToU8(SLICE_INFO) });
		const result = parseThreeMf(bytes);
		expect(result.map((f) => f.usedWeight)).toEqual([13, 4]);
	});

	it('throws a no_slice_info ThreeMfError when there is no slice info (an unsliced 3mf)', () => {
		const bytes = zipSync({ '3D/3dmodel.model': strToU8('<model/>') });
		expect(() => parseThreeMf(bytes)).toThrowError(expect.objectContaining({ code: 'no_slice_info' }));
	});

	it('throws an invalid_file ThreeMfError when the bytes are not a zip', () => {
		expect(() => parseThreeMf(new Uint8Array([1, 2, 3, 4]))).toThrowError(
			expect.objectContaining({ code: 'invalid_file' })
		);
	});
});

describe('spoolPrimaryHex', () => {
	it("uses the spool's filament colour", () => {
		const filaments = [filament('1', { colors: ['#FF0000'] })];
		expect(spoolPrimaryHex(spool(1, '1'), filaments)).toBe('#FF0000');
	});

	it('matches on the first colour of a multi-colour filament', () => {
		const filaments = [filament('1', { colors: ['#FF0000', '#00FF00'] })];
		expect(spoolPrimaryHex(spool(1, '1'), filaments)).toBe('#FF0000');
	});
});

describe('autoMatchSpoolId', () => {
	const filaments = [
		filament('f-pla-red', { material: 'PLA', colors: ['#FF0000'] }),
		filament('f-petg-red', { material: 'PETG', colors: ['#FF0000'] }),
		filament('f-pla-blue', { material: 'PLA', colors: ['#0000FF'] })
	];
	const spools = [spool(1, 'f-pla-red'), spool(2, 'f-petg-red'), spool(3, 'f-pla-blue')];

	it('prefers the colour match whose material also matches', () => {
		expect(
			autoMatchSpoolId({ key: '1', type: 'PETG', colorHex: '#FF0000', usedWeight: 5 }, spools, filaments)
		).toBe(2);
		expect(
			autoMatchSpoolId({ key: '1', type: 'PLA', colorHex: '#FF0000', usedWeight: 5 }, spools, filaments)
		).toBe(1);
	});

	it('falls back to any colour match when no material matches', () => {
		expect(
			autoMatchSpoolId({ key: '1', type: 'TPU', colorHex: '#FF0000', usedWeight: 5 }, spools, filaments)
		).toBe(1);
	});

	it('returns undefined when no spool colour matches', () => {
		expect(
			autoMatchSpoolId({ key: '1', type: 'PLA', colorHex: '#123456', usedWeight: 5 }, spools, filaments)
		).toBeUndefined();
	});

	it('matches on the filament colour', () => {
		const reds = [spool(9, 'f-pla-red')];
		expect(spoolPrimaryHex(reds[0], filaments)).toBe('#FF0000');
		expect(
			autoMatchSpoolId({ key: '1', type: 'PLA', colorHex: '#FF0000', usedWeight: 5 }, reds, filaments)
		).toBe(9);
	});

	it("matches a multi-colour filament's spool on its first colour", () => {
		const multiFilaments = [filament('f-multi', { material: 'PLA', colors: ['#FF0000', '#00FF00'] })];
		const multiSpools = [spool(4, 'f-multi')];
		expect(
			autoMatchSpoolId(
				{ key: '1', type: 'PLA', colorHex: '#FF0000', usedWeight: 5 },
				multiSpools,
				multiFilaments
			)
		).toBe(4);
	});

	it('never auto-matches a project filament with no colour attribute', () => {
		expect(
			autoMatchSpoolId({ key: '1', type: 'PLA', colorHex: undefined, usedWeight: 5 }, spools, filaments)
		).toBeUndefined();
	});

	it('compares material case-insensitively', () => {
		// A red PETG spool first: a case-sensitive comparison would find no material match and fall
		// back to it, so only a case-insensitive one picks spool 5.
		const lower = [
			filament('f-petg-red', { material: 'PETG', colors: ['#FF0000'] }),
			filament('f-lower', { material: 'PLA', colors: ['#FF0000'] })
		];
		const lowerSpools = [spool(6, 'f-petg-red'), spool(5, 'f-lower')];
		expect(
			autoMatchSpoolId({ key: '1', type: 'pla', colorHex: '#FF0000', usedWeight: 5 }, lowerSpools, lower)
		).toBe(5);
	});

	it('drops a filament whose used grams are not a number', () => {
		const xml = '<config><plate><filament id="1" type="PLA" color="#000000" used_g="abc"/></plate></config>';
		expect(parseSliceInfo(xml)).toEqual([]);
	});

	it('never merges a filament without an id into another row', () => {
		const xml =
			'<config><plate><filament id="2" type="PETG" color="#00FF00" used_g="4"/>' +
			'<filament type="PLA" color="#FF0000" used_g="5"/></plate></config>';
		expect(parseSliceInfo(xml).map((f) => [f.type, f.usedWeight])).toEqual([
			['PETG', 4],
			['PLA', 5]
		]);
	});
});
