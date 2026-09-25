/**
 * Print the inventory report (#414 step 1): a print-only root appended to the page and the
 * browser's print dialog, the technique the label designer uses (`lib/labels/print.ts`). Built
 * with DOM nodes and `textContent`, so a material name can never be read as markup.
 */
import type { InventoryReport } from './importExport';

export interface ReportLabels {
	heading: string;
	spools: string;
	remaining: string;
	value: string;
	material: string;
	count: string;
	weight: string;
	formatWeight: (grams: number) => string;
	formatValue: (value: number) => string;
}

const CSS = `
	@media screen { .inventory-report-root { display: none; } }
	@media print {
		@page { margin: 15mm; }
		html, body { background: #fff !important; }
		body > *:not(.inventory-report-root) { display: none !important; }
		.inventory-report-root { display: block !important; color: #000; font: 11pt system-ui, sans-serif; }
		.inventory-report-root h1 { font-size: 16pt; margin: 0 0 2mm; }
		.inventory-report-root .when { color: #444; margin: 0 0 6mm; }
		.inventory-report-root dl { display: grid; grid-template-columns: max-content max-content; gap: 1mm 8mm; margin: 0 0 6mm; }
		.inventory-report-root dt { color: #444; }
		.inventory-report-root dd { margin: 0; font-weight: 600; }
		.inventory-report-root table { border-collapse: collapse; }
		.inventory-report-root th, .inventory-report-root td { border-bottom: 0.3mm solid #999; padding: 1.5mm 4mm 1.5mm 0; text-align: left; }
		.inventory-report-root td.num, .inventory-report-root th.num { text-align: right; }
	}
`;

function el<K extends keyof HTMLElementTagNameMap>(
	tag: K,
	text?: string,
	cls?: string
): HTMLElementTagNameMap[K] {
	const e = document.createElement(tag);
	if (text !== undefined) e.textContent = text;
	if (cls) e.className = cls;
	return e;
}

/** Build the report's DOM. Separate from printing so it can be checked without a print dialog. */
export function buildReport(report: InventoryReport, labels: ReportLabels, when: Date): HTMLDivElement {
	const root = el('div', undefined, 'inventory-report-root');
	root.append(el('h1', labels.heading), el('p', when.toLocaleString(), 'when'));

	const dl = el('dl');
	for (const [k, v] of [
		[labels.spools, String(report.spoolCount)],
		[labels.remaining, labels.formatWeight(report.remainingWeight)],
		[labels.value, labels.formatValue(report.value)]
	]) {
		dl.append(el('dt', k), el('dd', v));
	}
	root.append(dl);

	const table = el('table');
	const head = el('tr');
	head.append(el('th', labels.material), el('th', labels.count, 'num'), el('th', labels.weight, 'num'));
	table.append(el('thead'), el('tbody'));
	table.tHead!.append(head);
	for (const m of report.materials) {
		const row = el('tr');
		row.append(
			el('td', m.material),
			el('td', String(m.count), 'num'),
			el('td', labels.formatWeight(m.weight), 'num')
		);
		table.tBodies[0].append(row);
	}
	root.append(table);
	return root;
}

export function printReport(report: InventoryReport, labels: ReportLabels): void {
	const root = buildReport(report, labels, new Date());
	const style = el('style', CSS);
	document.body.append(style, root);
	const cleanup = () => {
		root.remove();
		style.remove();
		window.removeEventListener('afterprint', cleanup);
	};
	window.addEventListener('afterprint', cleanup);
	window.print();
	// Fallback for browsers that do not fire afterprint.
	setTimeout(cleanup, 60000);
}
