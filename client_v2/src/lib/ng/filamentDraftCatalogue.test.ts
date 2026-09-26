import { describe, expect, it } from 'vitest';
import { filamentDraftFrom, toNewFilamentDraft } from '$lib/filament/draft';
import { EMPTY_FILAMENT_NG } from './filamentCatalogue';
import type { Filament } from '$lib/types';

/**
 * The fork's seams in upstream's `lib/filament/draft.ts`: a duplicate starts with its source's
 * catalogue fields, and they reach the create body. A later subtree pull that drops either line
 * fails here rather than only in the browser suite.
 */
describe('catalogue fields through the new-filament draft', () => {
	const source = {
		name: 'Galaxy Black',
		material: 'PLA',
		density: 1.24,
		diameter: 1.75,
		nozzleTemp: 210,
		bedTemp: 60,
		comment: '',
		ng: { ...EMPTY_FILAMENT_NG, finish: 'matte', translucent: false, hasImage: true }
	} as unknown as Filament;
	const weights = { weight: '1000', spoolWeight: '', price: '' };

	it('a duplicate carries them to the create body', () => {
		const body = toNewFilamentDraft(filamentDraftFrom(source, 'Prusament'), weights, {});
		expect(body.ng).toEqual({
			spoolType: null,
			finish: 'matte',
			pattern: null,
			translucent: false,
			glow: null
		});
	});

	it('a filament without them gives a draft without them', () => {
		const plain = { ...source, ng: undefined } as Filament;
		expect(toNewFilamentDraft(filamentDraftFrom(plain, ''), weights, {}).ng).toBeUndefined();
	});
});
