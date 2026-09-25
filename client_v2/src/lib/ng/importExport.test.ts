import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	exportFilename,
	formatFromFilename,
	importData,
	importEntityFor,
	importSucceeded,
	inventoryReport,
	parseImportResult
} from './importExport';
import type { Spool } from '$lib/types';
import type { ForkFilament } from '$lib/ng/types';

describe('names and formats', () => {
	it('maps each export entity to the import endpoint’s singular spelling', () => {
		expect(importEntityFor('spools')).toBe('spool');
		expect(importEntityFor('filaments')).toBe('filament');
		expect(importEntityFor('vendors')).toBe('vendor');
	});

	it('names exports as the classic client does', () => {
		expect(exportFilename('spools', 'csv')).toBe('spoolman-spools.csv');
	});

	it('reads the format from a file’s extension, case-insensitively', () => {
		expect(formatFromFilename('spoolman-spools.CSV')).toBe('csv');
		expect(formatFromFilename('backup.json')).toBe('json');
		expect(formatFromFilename('notes.txt')).toBeNull();
		expect(formatFromFilename('csv')).toBeNull();
	});
});

describe('parseImportResult', () => {
	it('reads the server’s counts and errors', () => {
		const r = parseImportResult({
			created: 2,
			updated: 1,
			skipped: 0,
			dry_run: true,
			errors: ['Row 3: bad']
		});
		expect(r).toEqual({ created: 2, updated: 1, skipped: 0, dryRun: true, errors: ['Row 3: bad'] });
		expect(importSucceeded(r)).toBe(false);
	});

	it('treats missing or malformed fields as zero or empty', () => {
		const r = parseImportResult({ created: 'x' });
		expect(r).toEqual({ created: 0, updated: 0, skipped: 0, dryRun: false, errors: [] });
		expect(importSucceeded(r)).toBe(true);
		expect(parseImportResult(null).errors).toEqual([]);
	});
});

describe('importData', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('posts the file text as the raw body, with the format, mode and dry run in the query', async () => {
		const fetch = vi.fn(
			async () =>
				new Response(JSON.stringify({ created: 1, updated: 0, skipped: 0, dry_run: true, errors: [] }))
		);
		vi.stubGlobal('fetch', fetch);
		const result = await importData('filament', 'csv', 'upsert', true, 'id,name\n1,PLA');
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toMatch(/\/import\/filament\?fmt=csv&mode=upsert&dry_run=true$/);
		expect(init.method).toBe('POST');
		expect(init.body).toBe('id,name\n1,PLA');
		expect((init.headers as Record<string, string>)['Content-Type']).toBe('text/csv');
		expect(result.created).toBe(1);
	});

	it('rejects with the server’s message on a refused import', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response(JSON.stringify({ message: 'Invalid JSON' }), { status: 400 }))
		);
		await expect(importData('spool', 'json', 'create', false, '{')).rejects.toThrow(/400: Invalid JSON/);
	});
});

describe('inventoryReport', () => {
	it('counts the spools and groups their stock by material, heaviest first', () => {
		const filaments = [
			{ id: '1', material: 'PLA', price: 20, weight: 1000 },
			{ id: '2', material: 'PETG', price: 0, weight: 1000 }
		] as unknown as ForkFilament[];
		const spools = [
			{ filamentId: '1', remaining: 300, initial: 1000 },
			{ filamentId: '1', remaining: 200, initial: 1000 },
			{ filamentId: '2', remaining: 900, initial: 1000 }
		] as unknown as Spool[];
		const r = inventoryReport(spools, filaments);
		expect(r.spoolCount).toBe(3);
		expect(r.materials.map((m) => m.material)).toEqual(['PETG', 'PLA']);
		expect(r.materials.find((m) => m.material === 'PLA')?.count).toBe(2);
	});
});
