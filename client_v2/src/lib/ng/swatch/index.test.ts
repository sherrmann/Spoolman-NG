// Ported from the classic client's client/src/utils/swatch/index.test.ts (#415 step 3).
// Adapted for client_v2: swatchInputFromFilament now takes client_v2's
// `Filament` view model ($lib/types) instead of the classic client's React
// `IFilament`, with vendor name always supplied via `options.vendorName`
// (client_v2's Filament carries only a vendorId, not a nested vendor object).
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Filament } from '$lib/types';
import {
	generateFilamentSwatch,
	saveBinaryFile,
	swatchFilename,
	swatchInputFromFilament,
	swatchTitle
} from './index';

const FILAMENT: Filament = {
	id: '42',
	vendorId: '1',
	name: 'Galaxy Black',
	material: 'PLA',
	colors: ['#aabbcc'],
	diameter: 1.75,
	density: 1.24,
	nozzleTemp: 215,
	bedTemp: 60,
	weight: 1000,
	price: 0,
	articleNumber: 'ART-42',
	comment: '',
	registeredLabel: 'Jan 1',
	tags: [],
	extra: {}
};

describe('swatchInputFromFilament', () => {
	it('maps the filament fields', () => {
		const input = swatchInputFromFilament(FILAMENT, {
			qrPayload: 'WEB+SPOOLMAN:F-42',
			vendorName: 'Prusament'
		});
		expect(input).toEqual({
			id: 42,
			name: 'Galaxy Black',
			vendorName: 'Prusament',
			material: 'PLA',
			diameterMm: 1.75,
			weightG: 1000,
			extruderTempC: 215,
			bedTempC: 60,
			articleNumber: 'ART-42',
			colorHexes: ['aabbcc'],
			qrPayload: 'WEB+SPOOLMAN:F-42'
		});
	});

	it('leaves vendorName undefined when none is given', () => {
		const input = swatchInputFromFilament(FILAMENT, { qrPayload: 'x' });
		expect(input.vendorName).toBeUndefined();
	});

	it('splits multi-color filaments into their component colors', () => {
		const input = swatchInputFromFilament(
			{ ...FILAMENT, colors: ['#112233', '#445566'] },
			{ qrPayload: 'x' }
		);
		expect(input.colorHexes).toEqual(['112233', '445566']);
	});

	it('turns empty strings into undefined', () => {
		const input = swatchInputFromFilament(
			{ ...FILAMENT, name: '', material: '', articleNumber: '' },
			{ qrPayload: 'x' }
		);
		expect(input.name).toBeUndefined();
		expect(input.material).toBeUndefined();
		expect(input.articleNumber).toBeUndefined();
	});

	it('does not print the "(unnamed filament)" screen label as a name', () => {
		// mapFilament shows a nameless filament under that label; the card leaves the name out
		// and is titled by its vendor, as in the classic client.
		const input = swatchInputFromFilament(
			{ ...FILAMENT, name: '(unnamed filament)' },
			{ qrPayload: 'x', vendorName: 'Acme' }
		);
		expect(input.name).toBeUndefined();
		expect(swatchFilename(input)).not.toContain('unnamed');
	});

	it('maps a missing (zero) temperature to undefined, as client_v2 stores no-temperature as 0', () => {
		const input = swatchInputFromFilament({ ...FILAMENT, nozzleTemp: 0, bedTemp: 0 }, { qrPayload: 'x' });
		expect(input.extruderTempC).toBeUndefined();
		expect(input.bedTempC).toBeUndefined();
	});

	it('also treats negative or non-finite temperatures as unset', () => {
		const input = swatchInputFromFilament({ ...FILAMENT, nozzleTemp: -1, bedTemp: NaN }, { qrPayload: 'x' });
		expect(input.extruderTempC).toBeUndefined();
		expect(input.bedTempC).toBeUndefined();
	});

	it("strips the leading # that client_v2 colors carry, matching the classic client's stored-hex format", () => {
		const input = swatchInputFromFilament({ ...FILAMENT, colors: ['#AABBCC'] }, { qrPayload: 'x' });
		expect(input.colorHexes).toEqual(['AABBCC']);
	});
});

describe('swatchTitle', () => {
	it('joins vendor and name', () => {
		expect(swatchTitle(swatchInputFromFilament(FILAMENT, { qrPayload: 'x', vendorName: 'Prusament' }))).toBe(
			'Prusament Galaxy Black'
		);
	});

	it('falls back to the filament id', () => {
		expect(swatchTitle({ id: 7, colorHexes: [], qrPayload: 'x' })).toBe('Filament #7');
	});
});

describe('swatchFilename', () => {
	const input = swatchInputFromFilament(FILAMENT, { qrPayload: 'x', vendorName: 'Prusament' });

	it('builds a descriptive, safe filename including the style', () => {
		expect(swatchFilename(input)).toBe('swatch_classic_42_Prusament_Galaxy_Black.3mf');
		expect(swatchFilename(input, 'compact')).toBe('swatch_compact_42_Prusament_Galaxy_Black.3mf');
	});

	it('strips unsafe characters and falls back to the default style for unknown keys', () => {
		const weird = { ...input, vendorName: 'Über/Cool GmbH & Co.', name: 'Näme "quoted"' };
		expect(swatchFilename(weird, 'no-such-style')).toBe('swatch_classic_42_berCool_GmbH__Co._Nme_quoted.3mf');
	});

	it('omits missing parts entirely', () => {
		expect(swatchFilename({ id: 7, colorHexes: [], qrPayload: 'x' })).toBe('swatch_classic_7.3mf');
	});
});

describe('generateFilamentSwatch', () => {
	it('produces a non-empty 3MF and a matching filename', () => {
		const input = swatchInputFromFilament(FILAMENT, {
			qrPayload: 'WEB+SPOOLMAN:F-42',
			vendorName: 'Prusament'
		});
		const { data, filename } = generateFilamentSwatch(input, 'card');
		expect(data.length).toBeGreaterThan(1000);
		expect(filename).toBe('swatch_card_42_Prusament_Galaxy_Black.3mf');
	});
});

describe('saveBinaryFile', () => {
	// client_v2's vitest runs in a plain node environment with no jsdom/happy-dom
	// dependency (unlike the classic client's jsdom-backed vitest config), and
	// this port may not add one. `document` isn't a real global here, so this
	// stubs a minimal fake instead of spying on `HTMLAnchorElement.prototype` —
	// same assertions (a temporary anchor is created, clicked once with the
	// right filename while attached, then removed, and the object URL is
	// revoked), just without a browser DOM to check them against.
	const originalCreateObjectURL = URL.createObjectURL;
	const originalRevokeObjectURL = URL.revokeObjectURL;

	afterEach(() => {
		URL.createObjectURL = originalCreateObjectURL;
		URL.revokeObjectURL = originalRevokeObjectURL;
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('downloads via a temporary anchor and revokes the object URL', () => {
		URL.createObjectURL = vi.fn(() => 'blob:mock-url');
		URL.revokeObjectURL = vi.fn();
		const appended: unknown[] = [];
		const anchor = {
			href: '',
			download: '',
			click: vi.fn(),
			remove: vi.fn(() => {
				const index = appended.indexOf(anchor);
				if (index >= 0) appended.splice(index, 1);
			})
		};
		const fakeDocument = {
			createElement: vi.fn(() => anchor),
			body: {
				appendChild: vi.fn((el: unknown) => appended.push(el)),
				contains: (el: unknown) => appended.includes(el)
			}
		};
		vi.stubGlobal('document', fakeDocument);
		anchor.click.mockImplementation(() => {
			expect(fakeDocument.body.contains(anchor)).toBe(true);
		});

		saveBinaryFile(new Uint8Array([1, 2, 3]), 'test.3mf');

		expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
		expect(anchor.click).toHaveBeenCalledTimes(1);
		expect(anchor.download).toBe('test.3mf');
		expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-url');
		expect(fakeDocument.body.contains(anchor)).toBe(false);
	});
});
