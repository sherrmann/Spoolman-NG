import { paraglideVitePlugin } from '@inlang/paraglide-js';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [
		sveltekit(),
		paraglideVitePlugin({
			project: './project.inlang',
			outdir: './src/lib/paraglide',
			strategy: ['localStorage', 'preferredLanguage', 'baseLocale']
		}),
		// Spoolman NG fork addition. This fork's own pages keep their strings in a second
		// inlang project so nothing of ours lands in ./locales, which upstream's Weblate
		// rewrites and `git subtree pull` would then conflict on. Same strategy list as
		// above on purpose: both runtimes read the PARAGLIDE_LOCALE localStorage key, so
		// the language picker in settings switches this fork's pages too.
		paraglideVitePlugin({
			project: './project-ng.inlang',
			outdir: './src/lib/paraglide-ng',
			strategy: ['localStorage', 'preferredLanguage', 'baseLocale']
		})
	],
	server: { port: 5174 },
	test: {
		// Unit tests only. The Playwright a11y audit lives in e2e/ and is run by
		// `npm run audit:a11y`; including it here would make vitest try to execute it.
		include: ['src/**/*.test.ts'],
		environment: 'node'
	}
});
