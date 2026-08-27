import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { handleScan } from './scanActions';
import { CLEAR_PAYLOAD } from './scanCodes';

/**
 * How a raw scan is routed. Every scan is offered to all three paths -- the CLEAR sentinel,
 * the entity parser, and the retail-barcode lookup -- so most of what matters here is that
 * they cannot claim each other's input, and that the lookup only ever runs when it should.
 */

const CLEAR_MSG = 'Clear-spool code recognized.';

// The lookup goes through $lib/api/http, which needs a base URL and fetch. Stub it: what is
// under test is the routing, not the transport.
vi.mock('$lib/api/http', () => ({
	getJson: vi.fn()
}));
const { getJson } = await import('$lib/api/http');
const mockGetJson = vi.mocked(getJson);

beforeEach(() => mockGetJson.mockReset());
afterEach(() => vi.clearAllMocks());

describe('the clear sentinel', () => {
	it('is acknowledged with the caller-supplied message', async () => {
		expect(await handleScan(CLEAR_PAYLOAD, 'open', null, CLEAR_MSG)).toEqual({
			kind: 'acknowledge',
			message: CLEAR_MSG
		});
	});

	it('is acknowledged in move mode too, without disturbing the held spool', async () => {
		expect(await handleScan(CLEAR_PAYLOAD, 'move', 7, CLEAR_MSG)).toEqual({
			kind: 'acknowledge',
			message: CLEAR_MSG
		});
	});

	it('never triggers a lookup', async () => {
		await handleScan(CLEAR_PAYLOAD, 'open', null, CLEAR_MSG);
		expect(mockGetJson).not.toHaveBeenCalled();
	});
});

describe('entity codes', () => {
	it('routes to the move state machine', async () => {
		expect(await handleScan('WEB+SPOOLMAN:S-7', 'open', null, CLEAR_MSG)).toEqual({
			kind: 'outcome',
			outcome: { kind: 'navigate', ref: { kind: 'spool', id: 7 } }
		});
		expect(await handleScan('WEB+SPOOLMAN:S-7', 'move', null, CLEAR_MSG)).toEqual({
			kind: 'outcome',
			outcome: { kind: 'capture_spool', spoolId: 7 }
		});
		expect(await handleScan('WEB+SPOOLMAN:L-3', 'move', 7, CLEAR_MSG)).toEqual({
			kind: 'outcome',
			outcome: { kind: 'propose_move', spoolId: 7, locationId: 3 }
		});
	});

	it('never triggers a lookup, even for an all-digit id', async () => {
		await handleScan('WEB+SPOOLMAN:S-12345678', 'open', null, CLEAR_MSG);
		expect(mockGetJson).not.toHaveBeenCalled();
	});
});

describe('retail barcodes', () => {
	it('offers to add a spool when one filament carries that article number', async () => {
		mockGetJson.mockResolvedValue([{ id: 42 }]);
		expect(await handleScan('1234567890123', 'open', null, CLEAR_MSG)).toEqual({
			kind: 'add_spool',
			filamentId: '42'
		});
	});

	it('quotes the term so the filter matches exactly, not as a substring', async () => {
		// Unquoted, 12345678 would also match 123456789 -- a different product.
		mockGetJson.mockResolvedValue([]);
		await handleScan('12345678', 'open', null, CLEAR_MSG);
		expect(mockGetJson).toHaveBeenCalledWith('/filament', { article_number: '"12345678"' }, undefined);
	});

	it('offers to create a filament when nothing matches', async () => {
		mockGetJson.mockResolvedValue([]);
		expect(await handleScan('1234567890123', 'open', null, CLEAR_MSG)).toEqual({
			kind: 'unknown_barcode',
			code: '1234567890123'
		});
	});

	it('reports a failed lookup rather than looking like no match', async () => {
		// A network error must not read as "no filament has this barcode", which would invite
		// the user to create a duplicate of one that already exists.
		// mockImplementation, not mockRejectedValue: the latter builds the rejected promise
		// eagerly, before anything can attach a handler, and Node flags it as unhandled even
		// though handleScan does catch it. Throwing inside the call keeps the rejection lazy.
		mockGetJson.mockImplementationOnce(async () => {
			throw new Error('offline');
		});
		expect(await handleScan('1234567890123', 'open', null, CLEAR_MSG)).toEqual({
			kind: 'lookup_failed'
		});
	});

	it('keeps the id a string, since filament ids are strings in this client', async () => {
		// CockroachDB ids exceed what a JS number holds exactly, which is why the domain types
		// them as strings. The narrowing itself happens in JSON.parse, upstream of any code
		// here -- writing an oversized literal in this file would just round at parse time and
		// prove nothing. What IS ours to get right is that the id is carried as a string rather
		// than a number, so a large one survives the rest of the trip; that is what this pins.
		mockGetJson.mockResolvedValue([{ id: 4242 }]);
		const effect = await handleScan('1234567890123', 'open', null, CLEAR_MSG);
		expect(effect).toEqual({ kind: 'add_spool', filamentId: '4242' });
	});

	it('is not consulted in move mode', async () => {
		// Interrupting a half-finished move with a filament dialog would lose the held spool.
		expect(await handleScan('1234567890123', 'move', 7, CLEAR_MSG)).toEqual({ kind: 'ignore' });
		expect(mockGetJson).not.toHaveBeenCalled();
	});

	it('is not consulted for a non-barcode-shaped scan', async () => {
		expect(await handleScan('hello world', 'open', null, CLEAR_MSG)).toEqual({ kind: 'ignore' });
		expect(mockGetJson).not.toHaveBeenCalled();
	});
});
