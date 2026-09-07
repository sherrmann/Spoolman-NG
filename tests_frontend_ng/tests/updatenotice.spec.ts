import { expect, test, type Page } from "@playwright/test";

/**
 * The once-per-release update notice (client_v2/src/lib/ng/components/UpdateNotice.svelte).
 *
 * `/info` is INTERCEPTED rather than trusted: whether the real backend reports an update is a
 * property of the release check reaching GitHub, which a CI runner or a sandbox cannot be
 * expected to do, and of what the newest release happens to be on the day the suite runs. The
 * route below fetches the real response and merges the three update fields into it, so
 * everything else on the page still sees the genuine `/info` this build needs.
 *
 * What is actually under test is the once-per-version rule, which is the whole feature: the card
 * appears for a version the user has not been told about, dismissing it records that version in
 * localStorage, and a later version gets through the same record. Each test runs in its own
 * browser context, so storage starts empty; the cases that turn on the key set or clear it
 * explicitly anyway, because the assertion is about that key and not about a fixture.
 */

const NOTIFIED_KEY = "spoolman-update-notified";
const RELEASE_URL = "https://example.invalid/releases/9.9.9";

/** Serve the real /info with the release check's answer merged in. */
async function stubInfo(page: Page, update: Record<string, unknown>) {
  await page.route("**/api/v1/info", async (route) => {
    const info = await (await route.fetch()).json();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...info, ...update }),
    });
  });
}

const notice = (page: Page) =>
  page.getByRole("status").filter({ hasText: "A new version of Spoolman is available" });

const readNotified = (page: Page) =>
  page.evaluate((key) => localStorage.getItem(key), NOTIFIED_KEY);

test("announces a release the user has not been told about", async ({ page }) => {
  await stubInfo(page, {
    update_available: true,
    latest_version: "9.9.9",
    release_url: RELEASE_URL,
  });

  await page.goto("/", { waitUntil: "networkidle" });

  const card = notice(page);
  await expect(card).toBeVisible();
  // The version is the point of the message: "an update is available" with no number tells the
  // user nothing they can act on.
  await expect(card).toContainText("9.9.9");

  const link = card.getByRole("link", { name: "View release notes" });
  await expect(link).toHaveAttribute("href", RELEASE_URL);
  await expect(link).toHaveAttribute("target", "_blank");
});

test("closing it keeps it closed for that version, across a reload", async ({ page }) => {
  await stubInfo(page, {
    update_available: true,
    latest_version: "9.9.9",
    release_url: RELEASE_URL,
  });

  await page.goto("/", { waitUntil: "networkidle" });
  await expect(notice(page)).toBeVisible();

  await notice(page).getByRole("button", { name: "Close" }).click();
  await expect(notice(page)).toHaveCount(0);

  // Dismissal is remembered as the version itself, which is what lets a *newer* one through.
  expect(await readNotified(page)).toBe("9.9.9");

  // The route is still installed, so the server is still offering 9.9.9 -- and it stays quiet.
  await page.reload({ waitUntil: "networkidle" });
  await expect(notice(page)).toHaveCount(0);
});

test("a newer release than the one dismissed is announced again", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  await page.evaluate((key) => localStorage.setItem(key, "9.9.9"), NOTIFIED_KEY);

  await stubInfo(page, {
    update_available: true,
    latest_version: "9.9.10",
    release_url: "https://example.invalid/releases/9.9.10",
  });

  await page.reload({ waitUntil: "networkidle" });
  await expect(notice(page)).toBeVisible();
  await expect(notice(page)).toContainText("9.9.10");
});

test("says nothing at all when the server reports no update", async ({ page }) => {
  await stubInfo(page, {
    update_available: false,
    latest_version: null,
    release_url: null,
  });

  await page.goto("/", { waitUntil: "networkidle" });
  await page.evaluate((key) => localStorage.removeItem(key), NOTIFIED_KEY);
  await page.reload({ waitUntil: "networkidle" });

  // Not a dismissed card and not an empty one: nothing is rendered.
  await expect(notice(page)).toHaveCount(0);
});
