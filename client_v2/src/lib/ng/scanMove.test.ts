import { describe, it, expect } from 'vitest';
import { decideScan } from './scanMove';
import type { ScannedRef } from '$lib/utils/spoolCode';

const spool = (id: number): ScannedRef => ({ kind: 'spool', id });
const location = (id: number): ScannedRef => ({ kind: 'location', id });
const filament = (id: number): ScannedRef => ({ kind: 'filament', id });

/**
 * The two-scan relocate flow. Every case here is one a user can reach by waving the wrong label
 * at the camera, which is exactly why this logic is pure -- none of it is reachable by a test
 * that has to drive a webcam.
 */

describe('open mode', () => {
	it('navigates to whatever was scanned', () => {
		expect(decideScan('open', null, spool(7))).toEqual({ kind: 'navigate', ref: spool(7) });
		expect(decideScan('open', null, location(3))).toEqual({ kind: 'navigate', ref: location(3) });
		expect(decideScan('open', null, filament(9))).toEqual({ kind: 'navigate', ref: filament(9) });
	});

	it('ignores a code that is not a Spoolman one', () => {
		expect(decideScan('open', null, null)).toEqual({ kind: 'ignore' });
	});

	it('never proposes a move, even with a spool somehow held', () => {
		// Guards against a mode leak: switching back to open with state left over must not
		// silently relocate anything.
		expect(decideScan('open', 7, location(3))).toEqual({ kind: 'navigate', ref: location(3) });
	});
});

describe('move mode, before a spool is held', () => {
	it('captures a scanned spool', () => {
		expect(decideScan('move', null, spool(7))).toEqual({ kind: 'capture_spool', spoolId: 7 });
	});

	it('asks for a spool when given anything else', () => {
		expect(decideScan('move', null, location(3))).toEqual({ kind: 'need_spool' });
		expect(decideScan('move', null, filament(9))).toEqual({ kind: 'need_spool' });
	});

	it('stays quiet on an unrecognised code rather than nagging', () => {
		// The camera sees every barcode in front of it, including ones that mean nothing here.
		expect(decideScan('move', null, null)).toEqual({ kind: 'ignore' });
	});
});

describe('move mode, holding a spool', () => {
	it('proposes the move when a location is scanned', () => {
		expect(decideScan('move', 7, location(3))).toEqual({
			kind: 'propose_move',
			spoolId: 7,
			locationId: 3
		});
	});

	it('ignores the held spool still sitting in the camera view', () => {
		// The label does not move just because the user is now hunting for a shelf; complaining
		// here would fire continuously while they walk.
		expect(decideScan('move', 7, spool(7))).toEqual({ kind: 'ignore' });
	});

	it('asks for a location when a DIFFERENT spool is scanned', () => {
		// Distinct from the case above: scanning another spool is a real mistake worth flagging,
		// not the same label lingering in frame.
		expect(decideScan('move', 7, spool(8))).toEqual({ kind: 'need_location' });
	});

	it('asks for a location when a filament is scanned', () => {
		expect(decideScan('move', 7, filament(9))).toEqual({ kind: 'need_location' });
	});

	it('still ignores an unrecognised code', () => {
		expect(decideScan('move', 7, null)).toEqual({ kind: 'ignore' });
	});
});

describe('the flow end to end', () => {
	it('walks spool then location to a proposed move', () => {
		const first = decideScan('move', null, spool(12));
		expect(first).toEqual({ kind: 'capture_spool', spoolId: 12 });
		const held = first.kind === 'capture_spool' ? first.spoolId : null;
		expect(decideScan('move', held, location(4))).toEqual({
			kind: 'propose_move',
			spoolId: 12,
			locationId: 4
		});
	});

	it('survives a wrong scan in the middle without losing the held spool', () => {
		// need_location carries no state, so the caller keeps holding 12 and can carry on.
		expect(decideScan('move', 12, filament(1))).toEqual({ kind: 'need_location' });
		expect(decideScan('move', 12, location(4))).toEqual({
			kind: 'propose_move',
			spoolId: 12,
			locationId: 4
		});
	});
});
