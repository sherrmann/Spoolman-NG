import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	IntakeError,
	extractFromPhoto,
	extractionRows,
	failureFor,
	handoffFor,
	intakeChoices,
	lookupCatalogueEntry,
	rawDraftFrom,
	type SpoolIntakeExtraction,
	type SpoolIntakeResult
} from './spoolIntake';
import { HttpError } from '$lib/api/http';

const extraction: SpoolIntakeExtraction = {
	vendor: 'Prusament',
	name: 'Galaxy Black',
	material: 'PLA',
	color_hex: null,
	weight_g: 1000,
	spool_weight_g: null,
	diameter_mm: 1.75,
	extruder_temp_c: 215,
	bed_temp_c: null,
	lot_nr: 'A123',
	article_number: null,
	confidence: 'high'
};

const result: SpoolIntakeResult = {
	extraction,
	matches: {
		library: [
			{
				kind: 'library',
				filament_id: 7,
				vendor: 'Prusament',
				name: 'Galaxy Black',
				material: 'PLA',
				match_percent: 97
			}
		],
		catalog: [
			{
				kind: 'catalog',
				external_id: 'prusament_pla_galaxyblack_1000_175',
				vendor: 'Prusament',
				name: 'Galaxy Black',
				material: 'PLA',
				match_percent: 92
			}
		]
	}
};

describe('extractionRows', () => {
	it('lists the non-null fields in the classic client’s order', () => {
		expect(extractionRows(extraction).map((r) => r.key)).toEqual([
			'vendor',
			'name',
			'material',
			'weight_g',
			'diameter_mm',
			'extruder_temp_c',
			'lot_nr',
			'confidence'
		]);
	});

	it('stringifies values and drops every null', () => {
		const rows = extractionRows({ ...extraction, weight_g: 750, vendor: null, name: null });
		expect(rows.find((r) => r.key === 'weight_g')?.value).toBe('750');
		expect(rows.some((r) => r.key === 'vendor' || r.key === 'name')).toBe(false);
	});

	it('keeps a zero rather than treating it as missing', () => {
		expect(extractionRows({ ...extraction, bed_temp_c: 0 }).find((r) => r.key === 'bed_temp_c')?.value).toBe(
			'0'
		);
	});
});

describe('intakeChoices', () => {
	it('puts library first, catalogue next and the raw extraction last', () => {
		const choices = intakeChoices(result);
		expect(choices.map((c) => c.value)).toEqual(['lib:7', 'cat:prusament_pla_galaxyblack_1000_175', 'raw']);
		expect(choices.map((c) => c.kind)).toEqual(['library', 'catalog', 'raw']);
		expect(choices[0].matchPercent).toBe(97);
	});

	it('offers only the raw extraction when nothing matched', () => {
		const choices = intakeChoices({ extraction, matches: { library: [], catalog: [] } });
		expect(choices.map((c) => c.value)).toEqual(['raw']);
	});
});

describe('handoffFor', () => {
	it('hands a library choice over as the filament id and the lot', () => {
		expect(handoffFor('lib:7', extraction)).toEqual({ kind: 'library', filamentId: '7', lot: 'A123' });
	});

	it('hands a catalogue choice over as the external id and the lot', () => {
		expect(handoffFor('cat:abc_1', extraction)).toEqual({
			kind: 'catalog',
			externalId: 'abc_1',
			lot: 'A123'
		});
	});

	it('reads a missing lot as null, so nothing is filled in', () => {
		expect(handoffFor('lib:7', { ...extraction, lot_nr: null })).toEqual({
			kind: 'library',
			filamentId: '7',
			lot: null
		});
	});

	it('maps the raw choice to a draft of strings, empty where the photo said nothing', () => {
		const handoff = handoffFor('raw', { ...extraction, color_hex: '#FF8800' });
		expect(handoff.kind).toBe('raw');
		if (handoff.kind !== 'raw') return;
		expect(handoff.draft).toEqual({
			vendorName: 'Prusament',
			name: 'Galaxy Black',
			material: 'PLA',
			weight: '1000',
			spoolWeight: '',
			diameter: '1.75',
			nozzleTemp: '215',
			bedTemp: '',
			colorHex: 'FF8800',
			articleNumber: '',
			lot: 'A123'
		});
		expect(rawDraftFrom(extraction).colorHex).toBe('');
	});
});

describe('failureFor', () => {
	it.each([
		[404, 'disabled'],
		[409, 'unconfigured'],
		[413, 'too_large'],
		[400, 'bad_image'],
		[502, 'failed'],
		[500, 'failed']
	])('maps status %i to %s', (status, failure) => {
		expect(failureFor(new HttpError('x', status))).toBe(failure);
	});

	it('maps a dropped connection to failed', () => {
		expect(failureFor(new TypeError('Failed to fetch'))).toBe('failed');
	});
});

describe('extractFromPhoto and lookupCatalogueEntry', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('posts the image and mime and returns the parsed result', async () => {
		const fetch = vi.fn(async () => new Response(JSON.stringify(result)));
		vi.stubGlobal('fetch', fetch);
		const out = await extractFromPhoto('AAAA', 'image/jpeg');
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toMatch(/\/ai\/spool-intake\/extract$/);
		expect(init.method).toBe('POST');
		expect(JSON.parse(String(init.body))).toEqual({ image_base64: 'AAAA', mime: 'image/jpeg' });
		expect(out.matches.library).toHaveLength(1);
	});

	it('rejects with the mapped failure for a refused request', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response(JSON.stringify({ detail: 'x' }), { status: 409 }))
		);
		await expect(extractFromPhoto('AAAA', 'image/jpeg')).rejects.toMatchObject({
			name: 'IntakeError',
			failure: 'unconfigured'
		});
		await expect(extractFromPhoto('AAAA', 'image/jpeg')).rejects.toBeInstanceOf(IntakeError);
	});

	it('rejects with an AbortError, not a failure, once the signal has fired', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response(JSON.stringify(result)))
		);
		const controller = new AbortController();
		const pending = extractFromPhoto('AAAA', 'image/jpeg', controller.signal);
		controller.abort();
		await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
	});

	it('looks a catalogue entry up by id and reads a miss or an error as null', async () => {
		const entry = { id: 'abc_1', manufacturer: 'Prusament', name: 'X', material: 'PLA', density: 1.24 };
		const fetch = vi.fn(async () => new Response(JSON.stringify([entry])));
		vi.stubGlobal('fetch', fetch);
		expect((await lookupCatalogueEntry('abc_1'))?.id).toBe('abc_1');
		expect((fetch.mock.calls[0] as unknown as [string])[0]).toMatch(/\/external\/filament\?id=abc_1$/);
		expect(await lookupCatalogueEntry('other')).toBeNull();
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('', { status: 500 }))
		);
		expect(await lookupCatalogueEntry('abc_1')).toBeNull();
	});
});
