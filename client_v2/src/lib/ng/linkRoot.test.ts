import { afterEach, describe, expect, it, vi } from 'vitest';

const resolveMock = vi.hoisted(() => vi.fn());
vi.mock('$app/paths', () => ({ resolve: resolveMock }));

import { linkRoot } from './linkRoot';

afterEach(() => {
	vi.unstubAllGlobals();
});

function atOrigin(basePath: string) {
	vi.stubGlobal('window', { location: { origin: 'https://host.example' } });
	resolveMock.mockReturnValue(basePath + '/');
}

describe('linkRoot', () => {
	it('uses a non-empty Base URL, trimming trailing slashes', () => {
		atOrigin('/spoolman');
		expect(linkRoot('https://spools.example.com/x//')).toBe('https://spools.example.com/x');
	});

	it('falls back to the bare origin when there is no base path', () => {
		atOrigin('');
		expect(linkRoot('')).toBe('https://host.example');
	});

	it('appends the base path under a sub-path deploy', () => {
		atOrigin('/spoolman');
		expect(linkRoot('')).toBe('https://host.example/spoolman');
	});

	it('keeps the bare origin under HA ingress', () => {
		atOrigin('/api/hassio_ingress/abc123');
		expect(linkRoot('')).toBe('https://host.example');
	});

	it('is SSR-safe: returns an empty string with no window', () => {
		vi.stubGlobal('window', undefined);
		expect(linkRoot('')).toBe('');
	});
});
