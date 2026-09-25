import { describe, expect, it } from 'vitest';
import {
	EMPTY_FILAMENT_NG,
	catalogueFromExternal,
	filamentNgPatchToApi,
	mapFilamentNg
} from './filamentCatalogue';

describe('mapFilamentNg', () => {
	it('reads all five fields', () => {
		expect(
			mapFilamentNg({
				spool_type: 'cardboard',
				finish: 'matte',
				pattern: 'sparkle',
				translucent: true,
				glow: false
			})
		).toEqual({
			spoolType: 'cardboard',
			finish: 'matte',
			pattern: 'sparkle',
			translucent: true,
			glow: false
		});
	});

	it('treats missing, null and unknown values as unknown, and keeps false distinct from null', () => {
		expect(mapFilamentNg({})).toEqual(EMPTY_FILAMENT_NG);
		expect(
			mapFilamentNg({ spool_type: 'wood', finish: 'satin', pattern: 1, translucent: 'yes', glow: null })
		).toEqual(EMPTY_FILAMENT_NG);
		expect(mapFilamentNg({ translucent: false }).translucent).toBe(false);
	});
});

describe('filamentNgPatchToApi', () => {
	it('sends only the fields in the patch, and null to clear one', () => {
		expect(filamentNgPatchToApi({ ng: { finish: 'glossy' } })).toEqual({ finish: 'glossy' });
		expect(filamentNgPatchToApi({ ng: { spoolType: null, glow: false } })).toEqual({
			spool_type: null,
			glow: false
		});
	});

	it('sends nothing for a patch without catalogue fields', () => {
		expect(filamentNgPatchToApi({})).toEqual({});
		expect(filamentNgPatchToApi({ ng: {} })).toEqual({});
	});
});

describe('catalogueFromExternal', () => {
	it('copies the catalogue fields of a SpoolmanDB entry, as the React client does', () => {
		expect(
			catalogueFromExternal({
				id: 'x',
				name: 'Galaxy Black',
				spool_type: 'plastic',
				finish: 'glossy',
				pattern: 'sparkle',
				translucent: false,
				glow: false
			})
		).toEqual({
			spool_type: 'plastic',
			finish: 'glossy',
			pattern: 'sparkle',
			translucent: false,
			glow: false
		});
	});

	it('leaves out what the entry does not have or this server does not accept', () => {
		expect(catalogueFromExternal({ id: 'x', finish: 'silk', spool_type: null })).toEqual({});
	});
});
