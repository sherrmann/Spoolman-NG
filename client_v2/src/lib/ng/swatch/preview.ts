// Ported from the classic client's client/src/components/swatchPreview.tsx (#415 step 3).
// Pure SVG-path helpers extracted from the React swatch preview component:
// used to render a true-to-scale 2D preview of a swatch layout.

import type { SwatchLayout } from './layout';

export function circleSubpath(cx: number, cy: number, r: number): string {
	return `M ${cx + r} ${cy} A ${r} ${r} 0 1 0 ${cx - r} ${cy} A ${r} ${r} 0 1 0 ${cx + r} ${cy} Z`;
}

/**
 * Card outline as an SVG path: rounded rectangle, with the hanger-tab arch on
 * the top edge when present, minus any hole (even-odd fill).
 */
export function basePathD(layout: SwatchLayout): string {
	const { widthMm: w, heightMm: h, hangerTab } = layout;
	const r = Math.max(0, Math.min(layout.cornerRadiusMm, w / 2, h / 2));
	const topEdge = hangerTab
		? `H ${hangerTab.cx - hangerTab.outerR} ` +
			`A ${hangerTab.outerR} ${hangerTab.outerR} 0 0 1 ${hangerTab.cx + hangerTab.outerR} 0 H ${w - r}`
		: `H ${w - r}`;
	const outline =
		`M ${r} 0 ${topEdge} A ${r} ${r} 0 0 1 ${w} ${r} V ${h - r} A ${r} ${r} 0 0 1 ${w - r} ${h} ` +
		`H ${r} A ${r} ${r} 0 0 1 0 ${h - r} V ${r} A ${r} ${r} 0 0 1 ${r} 0 Z`;
	const holes = [
		layout.hole ? circleSubpath(layout.hole.cx, layout.hole.cy, layout.hole.r) : '',
		hangerTab ? circleSubpath(hangerTab.cx, 0, hangerTab.holeR) : ''
	];
	return [outline, ...holes].filter(Boolean).join(' ');
}
