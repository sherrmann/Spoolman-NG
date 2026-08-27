import { describe, it, expect } from 'vitest';
import { qrContent, qrTemplate } from '$lib/labels/qr';
import { resolveTemplate, getPlaceholderGroups } from '$lib/labels/template';
import { setDesignKind, newDesign, DEFAULT_LOCATION_TEXT } from '$lib/labels/types';
import type { LabelElement, QrElement, TextElement } from '$lib/labels/types';
import type { Location } from './types';

/**
 * The `location` label kind (#84), which this fork adds to upstream's label designer.
 *
 * These live under src/lib/ng/ rather than beside the code they exercise: everything in
 * src/lib/labels/ is vendored from upstream via git subtree, and a fork-authored test file
 * dropped in there would collide with any upstream file that ever takes the same name. The
 * import path reaches into the vendored module; the file itself stays ours.
 *
 * The contract worth pinning is the QR payload. A location label is only useful if a scanner
 * resolves it, and this fork's React client has printed `WEB+SPOOLMAN:L-<id>` (and the
 * `/location/show/<id>` URL form) since #84 -- see
 * client/src/pages/printing/locationQrCodePrintingDialog.tsx. If either string drifts, labels
 * already stuck on physical shelves stop working, which no typecheck would notice.
 */

const qr = (encoding: QrElement['encoding']): QrElement => ({
	id: 'q1',
	type: 'qr',
	x: 0,
	y: 0,
	size: 20,
	ec: 'H',
	logo: false,
	encoding
});

const location: Location = {
	id: 42,
	name: 'Bay A',
	comment: 'north wall',
	spoolCount: 3,
	extra: { shelf_note: '"top two rows"' }
};

describe('location QR payloads', () => {
	it('encodes the compact scheme with the L prefix the React client prints', () => {
		expect(qrContent(qr('scheme'), 42, { baseUrl: '', kind: 'location' })).toBe('WEB+SPOOLMAN:L-42');
	});

	it('encodes the URL form as the route the fork actually serves', () => {
		expect(qrContent(qr('url'), 42, { baseUrl: 'https://spool.example', kind: 'location' })).toBe(
			'https://spool.example/location/show/42'
		);
	});

	it('does not fall back to the spool prefix, the way a two-way test would', () => {
		// The pre-change code asked `kind === 'filament' ? F : S`, so any third kind silently
		// meant "spool". This is the regression that would make a location label open a spool.
		const scheme = qrTemplate(qr('scheme'), { baseUrl: '', kind: 'location' });
		expect(scheme.startsWith('WEB+SPOOLMAN:S-')).toBe(false);
		expect(scheme.startsWith('WEB+SPOOLMAN:F-')).toBe(false);
	});
});

describe('location templates', () => {
	it('resolves the location tokens from a bound row', () => {
		expect(resolveTemplate('{location.name} · #{location.id}', { location })).toBe('Bay A · #42');
		expect(resolveTemplate('{location.spoolCount}', { location })).toBe('3');
		expect(resolveTemplate('{location.comment}', { location })).toBe('north wall');
	});

	it('reads a location custom field the same way the other entities do', () => {
		expect(resolveTemplate('{location.extra.shelf_note}', { location })).toBe('top two rows');
	});

	it('drops a conditional block when the row has no comment', () => {
		const bare: Location = { id: 7, name: 'Bay B', extra: {} };
		expect(resolveTemplate('{location.name}{ · {location.comment}}', { location: bare })).toBe('Bay B');
	});

	it('leaves no unfillable field behind when a fresh design switches to location', () => {
		// newDesign() lays out three text blocks -- a manufacturer line, the filament name, and
		// a material-and-id line. Only the last was in the retarget table originally, so a
		// location label kept a vendor line and a filament line that resolve to "?" forever.
		const design = newDesign('d1');
		setDesignKind(design, 'location');
		const templates = design.elements
			.filter((e): e is TextElement => e.type === 'text')
			.map((e) => e.template);

		expect(templates.join(' ')).not.toMatch(/vendor\.|filament\.|spool\./);
		expect(templates).toContain('{location.name}');
		expect(templates).toContain('#{location.id}');
	});

	it('switches a single-block design to the combined location default', () => {
		const design = newDesign('d2');
		// Collapse to the older one-block shape DEFAULT_LOCATION_TEXT is the counterpart of.
		// The block is built from a REAL default text element with only its template swapped,
		// rather than hand-written, so this test cannot drift out of shape as TextElement gains
		// fields.
		const texts = design.elements.filter((e): e is TextElement => e.type === 'text');
		const oneBlock: LabelElement[] = [
			...design.elements.filter((e) => e.type !== 'text'),
			{ ...texts[0], template: '**{filament.name}**\n{filament.material}\n#{spool.id}' }
		];
		design.elements = oneBlock;
		setDesignKind(design, 'location');
		expect(
			design.elements.filter((e): e is TextElement => e.type === 'text').map((e) => e.template)
		).toContain(DEFAULT_LOCATION_TEXT);
	});

	it('round-trips spool and filament unchanged, which the new entries must not disturb', () => {
		const design = newDesign('d3');
		const before = design.elements.filter((e): e is TextElement => e.type === 'text').map((e) => e.template);
		setDesignKind(design, 'filament');
		setDesignKind(design, 'spool');
		const after = design.elements.filter((e): e is TextElement => e.type === 'text').map((e) => e.template);
		expect(after).toEqual(before);
	});
});

describe('the location palette', () => {
	it('offers only location tokens, since a location binds nothing else', () => {
		const groups = getPlaceholderGroups({}, 'location');
		expect(groups.map((g) => g.entity)).toEqual(['location']);
	});

	it('keeps location tokens off the spool and filament palettes', () => {
		// A spool label can never fill them: there is no foreign key from a spool's location
		// STRING to a Location row, so nothing to resolve through.
		for (const kind of ['spool', 'filament'] as const) {
			expect(getPlaceholderGroups({}, kind).map((g) => g.entity)).not.toContain('location');
		}
	});

	it('merges location custom fields into the palette when defined', () => {
		const groups = getPlaceholderGroups(
			{
				location: [
					{
						key: 'shelf_note',
						name: 'Shelf note',
						order: 0,
						field_type: 'text',
						entity_type: 'location'
					} as never
				]
			},
			'location'
		);
		expect(groups[0].items.map((i) => i.token)).toContain('location.extra.shelf_note');
	});
});
