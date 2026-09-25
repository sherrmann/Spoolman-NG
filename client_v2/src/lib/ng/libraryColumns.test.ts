import { describe, expect, it } from 'vitest';
import {
	MAX_WIDTH,
	MIN_WIDTH,
	clampWidth,
	effectiveOrder,
	gridTemplate,
	initialConfig,
	minGridWidth,
	moveColumn,
	normaliseConfig,
	parseStoredColumns,
	visibleColumns
} from './libraryColumns';

const CATALOGUE = ['id', 'swatch', 'name', 'material', 'progress', 'remaining', 'location', 'lot'];

describe('effectiveOrder', () => {
	it('keeps the saved order for columns that still exist', () => {
		expect(effectiveOrder(['location', 'id', 'name'], ['id', 'name', 'location'])).toEqual([
			'location',
			'id',
			'name'
		]);
	});

	it('appends columns the saved order has never seen, in catalogue order', () => {
		expect(effectiveOrder(['name', 'id'], ['id', 'name', 'lot', 'extra.grade'])).toEqual([
			'name',
			'id',
			'lot',
			'extra.grade'
		]);
	});

	it('drops ids the catalogue no longer has, and duplicates', () => {
		expect(effectiveOrder(['extra.gone', 'id', 'id', 'name'], ['id', 'name'])).toEqual(['id', 'name']);
	});
});

describe('initialConfig', () => {
	it('starts from upstream’s row: its columns shown, in its order, the rest hidden', () => {
		const config = initialConfig(CATALOGUE);
		expect(visibleColumns(config, CATALOGUE)).toEqual([
			'id',
			'swatch',
			'name',
			'progress',
			'remaining',
			'location'
		]);
		expect(config.hidden.sort()).toEqual(['lot', 'material']);
	});
});

describe('visibleColumns', () => {
	it('leaves out hidden columns', () => {
		const config = { order: ['id', 'name', 'lot'], hidden: ['id'], widths: {} };
		expect(visibleColumns(config, ['id', 'name', 'lot'])).toEqual(['name', 'lot']);
	});

	it('always shows the name, even when a stored configuration hides it or never saw it', () => {
		expect(visibleColumns({ order: ['id', 'name'], hidden: ['name'], widths: {} }, ['id', 'name'])).toEqual([
			'id',
			'name'
		]);
		expect(visibleColumns({ order: ['id'], hidden: [], widths: {} }, ['id', 'name'])).toEqual(['id', 'name']);
		expect(normaliseConfig({ order: [], hidden: ['name'], widths: {} }, ['id', 'name']).hidden).toEqual([
			'id'
		]);
	});

	it('does not show a column added after the configuration was saved', () => {
		// A new extra field should not appear in everyone's list uninvited.
		const config = { order: ['id', 'name'], hidden: [], widths: {} };
		expect(visibleColumns(config, ['id', 'name', 'extra.grade'])).toEqual(['id', 'name']);
	});
});

describe('moveColumn', () => {
	it('swaps with the neighbour', () => {
		expect(moveColumn(['a', 'b', 'c'], 'b', -1)).toEqual(['b', 'a', 'c']);
		expect(moveColumn(['a', 'b', 'c'], 'b', 1)).toEqual(['a', 'c', 'b']);
	});

	it('does nothing past either end, or for an unknown id', () => {
		expect(moveColumn(['a', 'b'], 'a', -1)).toEqual(['a', 'b']);
		expect(moveColumn(['a', 'b'], 'b', 1)).toEqual(['a', 'b']);
		expect(moveColumn(['a', 'b'], 'z', 1)).toEqual(['a', 'b']);
	});
});

describe('clampWidth', () => {
	it('keeps widths within a usable range', () => {
		expect(clampWidth(5)).toBe(MIN_WIDTH);
		expect(clampWidth(10_000)).toBe(MAX_WIDTH);
		expect(clampWidth(123.6)).toBe(124);
		expect(clampWidth(Number.NaN)).toBe(MIN_WIDTH);
	});
});

describe('gridTemplate', () => {
	it('gives every column a fixed width except the name, which takes the rest', () => {
		expect(gridTemplate(['id', 'name', 'lot'], { lot: 90 }, { id: 36, name: 160, lot: 80 })).toBe(
			'36px minmax(160px, 1fr) 90px'
		);
	});
});

describe('parseStoredColumns', () => {
	it('reads back a stored configuration, clamping widths', () => {
		expect(parseStoredColumns('{"order":["id"],"hidden":["lot"],"widths":{"id":2,"name":150}}')).toEqual({
			order: ['id'],
			hidden: ['lot'],
			widths: { id: MIN_WIDTH, name: 150 }
		});
	});

	it('treats anything else as nothing stored, which is upstream’s row', () => {
		for (const raw of [
			null,
			'',
			'junk',
			'[]',
			'null',
			'{"order":"id","hidden":[]}',
			'{"order":[1],"hidden":[]}'
		]) {
			expect(parseStoredColumns(raw)).toBeNull();
		}
	});

	it('drops widths that are not numbers', () => {
		expect(parseStoredColumns('{"order":[],"hidden":[],"widths":{"id":"wide","lot":80}}')?.widths).toEqual({
			lot: 80
		});
	});
});

describe('normaliseConfig', () => {
	it('starts from upstream’s row when nothing is stored', () => {
		expect(normaliseConfig(null, CATALOGUE)).toEqual(initialConfig(CATALOGUE));
	});

	it('hides a column the saved configuration has never seen, so switching it on works', () => {
		const catalogue = ['id', 'name', 'extra.grade'];
		const c = normaliseConfig({ order: ['name', 'id'], hidden: [], widths: { id: 50 } }, catalogue);
		expect(c).toEqual({ order: ['name', 'id', 'extra.grade'], hidden: ['extra.grade'], widths: { id: 50 } });
		expect(visibleColumns(c, catalogue)).toEqual(['name', 'id']);
		expect(visibleColumns({ ...c, hidden: [] }, catalogue)).toEqual(['name', 'id', 'extra.grade']);
	});
});

describe('minGridWidth', () => {
	it('adds the columns, the gaps between them, the padding and the border', () => {
		// 36 + 100 + 90 = 226; two gaps of 9; 14 padding each side; 2 border.
		expect(minGridWidth(['id', 'name', 'lot'], { lot: 90 }, { id: 36, name: 100, lot: 80 })).toBe(
			226 + 18 + 28 + 2
		);
	});
});
