// Ported from the classic client's client/src/components/swatchPreview.tsx (#415 step 3).
import { describe, expect, it } from 'vitest';
import { basePathD, circleSubpath } from './preview';
import { buildSwatchLayoutForStyle } from './styles';
import type { SwatchInput } from './layout';

const INPUT: SwatchInput = {
	id: 1,
	colorHexes: [],
	qrPayload: 'WEB+SPOOLMAN:F-1'
};

describe('circleSubpath', () => {
	it('draws a closed circle path', () => {
		const d = circleSubpath(5, 5, 2);
		expect(d.startsWith('M 7 5')).toBe(true);
		expect(d.endsWith('Z')).toBe(true);
		expect(d).toContain('A 2 2 0 1 0');
	});
});

describe('basePathD', () => {
	it('gives one closed subpath for a layout without a hole or hanger tab', () => {
		const layout = buildSwatchLayoutForStyle(INPUT, 'classic');
		const d = basePathD(layout);
		const subpaths = d.split(' Z').filter((s) => s.trim() !== '');
		expect(subpaths).toHaveLength(1);
		expect(d.trim().startsWith('M')).toBe(true);
	});

	it("includes the hole's circle subpath for a keychain-hole style", () => {
		const layout = buildSwatchLayoutForStyle(INPUT, 'keychain');
		expect(layout.hole).toBeDefined();
		const d = basePathD(layout);
		const expectedHole = circleSubpath(layout.hole!.cx, layout.hole!.cy, layout.hole!.r);
		expect(d).toContain(expectedHole);
		// outline plus hole = two closed subpaths
		const subpaths = d.split(' Z').filter((s) => s.trim() !== '');
		expect(subpaths).toHaveLength(2);
	});

	it("includes the hanger tab's nail-hole circle subpath for a hanger style", () => {
		const layout = buildSwatchLayoutForStyle(INPUT, 'hanger');
		expect(layout.hangerTab).toBeDefined();
		const d = basePathD(layout);
		const expectedHole = circleSubpath(layout.hangerTab!.cx, 0, layout.hangerTab!.holeR);
		expect(d).toContain(expectedHole);
	});
});
