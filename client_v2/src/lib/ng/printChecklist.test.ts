import { describe, expect, it } from 'vitest';
import {
	SKIP_PRINT_CHECKLIST_KEY,
	checklistPaper,
	rememberSkipPrintChecklist,
	shouldSkipPrintChecklist
} from './printChecklist';
import { DEFAULT_LAYOUT, type PrintLayout } from '$lib/labels/types';

/**
 * The checklist's opt-out flag and the page size it reports. Both are the parts that can be
 * wrong without anything looking wrong: a flag read too leniently silences the dialog for
 * good, and a page size that disagrees with what `printLabels()` asks the browser for tells
 * the user to select the wrong paper.
 */

// Same in-memory Storage as authToken.test.ts, so a test never depends on a real browser.
function fakeStorage(): Storage {
	const data = new Map<string, string>();
	return {
		getItem: (k: string) => data.get(k) ?? null,
		setItem: (k: string, v: string) => void data.set(k, v),
		removeItem: (k: string) => void data.delete(k),
		clear: () => data.clear(),
		key: () => null,
		get length() {
			return data.size;
		}
	} as Storage;
}

const layout = (over: Partial<PrintLayout> = {}): PrintLayout => ({ ...DEFAULT_LAYOUT, ...over });
const design = { label: { w: 62, h: 29 } };

describe('the opt-out flag', () => {
	it("is stored under this client's own key", () => {
		expect(SKIP_PRINT_CHECKLIST_KEY).toBe('spoolman-v2-skip-print-checklist');
	});

	it('does not skip the checklist when nothing has been stored', () => {
		expect(shouldSkipPrintChecklist(fakeStorage())).toBe(false);
	});

	it('does not skip on a value this client never wrote', () => {
		const storage = fakeStorage();
		for (const junk of ['0', 'true', 'yes', '', '{}']) {
			storage.setItem(SKIP_PRINT_CHECKLIST_KEY, junk);
			expect(shouldSkipPrintChecklist(storage)).toBe(false);
		}
	});

	it('skips once the opt-out has been remembered', () => {
		const storage = fakeStorage();
		rememberSkipPrintChecklist(storage);
		expect(storage.getItem(SKIP_PRINT_CHECKLIST_KEY)).toBe('1');
		expect(shouldSkipPrintChecklist(storage)).toBe(true);
	});

	it('leaves the checklist in place when storage refuses to answer', () => {
		const broken = {
			getItem: () => {
				throw new Error('storage disabled');
			},
			setItem: () => {
				throw new Error('storage disabled');
			}
		} as unknown as Storage;
		expect(() => rememberSkipPrintChecklist(broken)).not.toThrow();
		expect(shouldSkipPrintChecklist(broken)).toBe(false);
	});
});

describe('the page size the checklist reports', () => {
	it('is the label itself in label mode, where one label is one page', () => {
		expect(checklistPaper(design, layout({ mode: 'label' }))).toEqual({ w: 62, h: 29 });
	});

	it('is the sheet, not the label, in sheet mode', () => {
		expect(checklistPaper(design, layout({ mode: 'sheet', paper: 'A4' }))).toEqual({ w: 210, h: 297 });
	});

	it('resolves a custom sheet size', () => {
		expect(
			checklistPaper(design, layout({ mode: 'sheet', paper: 'custom', custom: { w: 100, h: 150 } }))
		).toEqual({ w: 100, h: 150 });
	});

	it('swaps the sheet dimensions for landscape', () => {
		expect(checklistPaper(design, layout({ mode: 'sheet', paper: 'A4', landscape: true }))).toEqual({
			w: 297,
			h: 210
		});
	});

	it('leaves a landscape label alone -- label mode prints the label, not the paper', () => {
		expect(checklistPaper(design, layout({ mode: 'label', landscape: true }))).toEqual({
			w: 62,
			h: 29
		});
	});
});
