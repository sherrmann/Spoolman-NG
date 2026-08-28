import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { shouldShowUiSwitcher, switchUiClient } from './uiClient';

describe('shouldShowUiSwitcher', () => {
	it('shows the control when switching is enabled and both bundles are built', () => {
		expect(shouldShowUiSwitcher(true, ['react', 'svelte'])).toBe(true);
		// Order in the list doesn't matter, only membership.
		expect(shouldShowUiSwitcher(true, ['svelte', 'react'])).toBe(true);
	});

	it('hides the control when the operator disabled switching', () => {
		expect(shouldShowUiSwitcher(false, ['react', 'svelte'])).toBe(false);
	});

	it('hides the control when only one bundle is built (a source install)', () => {
		expect(shouldShowUiSwitcher(true, ['react'])).toBe(false);
		expect(shouldShowUiSwitcher(true, ['svelte'])).toBe(false);
	});

	it('hides the control when /info has not loaded yet, or is silent on the older fields', () => {
		// $lib/stores/serverInfo defaults clientSwitchEnabled to false and clientsAvailable
		// to [] until /info answers -- and stays there forever against an older backend that
		// never sends these fields at all.
		expect(shouldShowUiSwitcher(false, [])).toBe(false);
	});
});

describe('switchUiClient', () => {
	let reload: ReturnType<typeof vi.fn>;
	let doc: { cookie: string };

	beforeEach(() => {
		reload = vi.fn();
		doc = { cookie: '' };
		vi.stubGlobal('document', doc);
		vi.stubGlobal('location', { reload });
	});

	afterEach(() => vi.unstubAllGlobals());

	it('writes the spoolman_ui cookie with the chosen target', () => {
		switchUiClient('react');
		expect(doc.cookie).toBe('spoolman_ui=react; path=/; max-age=31536000; SameSite=Lax');
	});

	it('writes either recognised target verbatim', () => {
		switchUiClient('svelte');
		expect(doc.cookie).toBe('spoolman_ui=svelte; path=/; max-age=31536000; SameSite=Lax');
	});

	it('sets a one-year max-age, matching the contract both clients write to', () => {
		switchUiClient('react');
		expect(doc.cookie).toContain('max-age=31536000');
	});

	it('reloads the page so the backend serves the newly-chosen client', () => {
		switchUiClient('svelte');
		expect(reload).toHaveBeenCalledTimes(1);
	});
});
