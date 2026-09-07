/**
 * The pre-print checklist's state and geometry (#296).
 *
 * A label preview is geometrically exact, but the browser's own print dialog can silently
 * undo that: fit-to-page scaling, the wrong paper picked, driver margins, headers and
 * footers. The checklist is shown between the panel's Print button and `window.print()`,
 * which is the only moment those settings are about to be applied. Everything here is pure
 * so it can be tested without a DOM; the dialog itself is
 * `$lib/ng/components/PrePrintChecklist.svelte`.
 */
import { paperSize } from '$lib/labels/paper';
import type { LabelDesign, PrintLayout } from '$lib/labels/types';

/**
 * Where the "don't show this again" opt-out is remembered, as a raw `'1'` validated on read
 * -- the same shape as `spoolman-v2-adjust-mode` in the spool inspector.
 *
 * The React client stores the same opt-out as `savedStates-print-skipPrintChecklist`, under
 * the prefix its own `useSavedState` hook owns. Sharing that literal would mean writing a key
 * that only makes sense inside another client's storage convention, so this client keeps its
 * own; the two opt-outs are independent, which is the honest answer anyway because the two
 * print paths are different code.
 */
export const SKIP_PRINT_CHECKLIST_KEY = 'spoolman-v2-skip-print-checklist';

/** Whether the user has opted out of the checklist. Anything but the exact flag is a no. */
export function shouldSkipPrintChecklist(storage: Storage): boolean {
	try {
		return storage.getItem(SKIP_PRINT_CHECKLIST_KEY) === '1';
	} catch {
		// Private browsing and "block site data" both throw here. A checklist that cannot be
		// dismissed permanently is a far smaller problem than a print button that throws.
		return false;
	}
}

/** Remember the opt-out. Called only when the user proceeds, never when they cancel. */
export function rememberSkipPrintChecklist(storage: Storage): void {
	try {
		storage.setItem(SKIP_PRINT_CHECKLIST_KEY, '1');
	} catch {
		// As above: the opt-out simply does not stick, and the checklist appears again.
	}
}

/**
 * The page size, in mm, that the next print will ask the browser for -- the number the
 * checklist tells the user to select in the print dialog.
 *
 * This has to mirror `printLabels()`: `label` mode emits one page per label at the design's
 * own size, everything else emits the resolved paper (`paperSize` honours a custom size and
 * landscape). `image` mode never reaches here -- it downloads files instead of printing, and
 * the panel renders a different button for it -- so it falls in with the sheet case rather
 * than being given a meaningless answer of its own.
 */
export function checklistPaper(
	design: Pick<LabelDesign, 'label'>,
	layout: PrintLayout
): { w: number; h: number } {
	return layout.mode === 'label' ? { w: design.label.w, h: design.label.h } : paperSize(layout);
}
