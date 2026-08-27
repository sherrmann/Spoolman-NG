import { test as base, chromium, type Browser, type Page } from "@playwright/test";
import { writeQrVideo } from "./qrVideo";

/**
 * A page whose camera is a QR code of our choosing.
 *
 * Chromium takes the fake capture file as a LAUNCH argument, so this cannot be a `test.use({
 * launchOptions })` override: the payloads name database ids that only exist once the test has
 * seeded them, and `test.use` values are fixed when the file is loaded. Launching per call is
 * what lets a payload be built from a row created moments earlier.
 *
 * Every browser opened through the fixture is closed when the test ends, whether it passed or
 * not -- a leaked headless chromium holding a camera outlives the run.
 */
export const test = base.extend<{ cameraPage: (payloads: string[]) => Promise<Page> }>({
	cameraPage: async ({ baseURL }, use) => {
		const opened: Browser[] = [];
		await use(async (payloads: string[]) => {
			const browser = await chromium.launch({
				executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH,
				args: [
					// Answer the permission prompt, swap the camera for a file, and name the file.
					"--use-fake-ui-for-media-stream",
					"--use-fake-device-for-media-stream",
					`--use-file-for-fake-video-capture=${writeQrVideo(payloads)}`,
				],
			});
			opened.push(browser);
			const context = await browser.newContext({
				baseURL,
				locale: "en-US",
				permissions: ["camera"],
				// The PWA precache otherwise serves a stale index.html and the page renders blank.
				serviceWorkers: "block",
			});
			return context.newPage();
		});
		for (const browser of opened) await browser.close();
	},
});

export { expect } from "@playwright/test";
