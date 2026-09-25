import { describe, expect, it } from 'vitest';
import { MAX_IMAGE_DIMENSION, fitWithin } from './filamentImage';

// The downscale target for reference-photo uploads, ported with the classic client's tests. The
// contract: fit inside the square bound, keep the aspect ratio, never upscale, never emit a zero
// dimension. The canvas half is browser-only and covered by the Playwright spec.
describe('fitWithin', () => {
	it('returns small and boundary-sized images unchanged', () => {
		expect(fitWithin(800, 600, 1024)).toEqual({ width: 800, height: 600 });
		expect(fitWithin(1024, 1024, 1024)).toEqual({ width: 1024, height: 1024 });
	});

	it('never upscales a tiny image', () => {
		expect(fitWithin(10, 20, 1024)).toEqual({ width: 10, height: 20 });
	});

	it('scales a landscape or portrait photo by its longer edge, keeping the aspect ratio', () => {
		expect(fitWithin(4032, 3024, 1024)).toEqual({ width: 1024, height: 768 });
		expect(fitWithin(3024, 4032, 1024)).toEqual({ width: 768, height: 1024 });
	});

	it('bounds both axes when both exceed the limit', () => {
		expect(fitWithin(5000, 2000, 1024)).toEqual({ width: 1024, height: 410 });
	});

	it('never rounds an extreme aspect ratio down to zero', () => {
		expect(fitWithin(10000, 1, 1024)).toEqual({ width: 1024, height: 1 });
	});

	it('uses the shared upload bound', () => {
		expect(fitWithin(MAX_IMAGE_DIMENSION * 2, MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION).width).toBe(
			MAX_IMAGE_DIMENSION
		);
	});
});
