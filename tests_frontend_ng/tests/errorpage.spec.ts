import { expect, test, type Page } from "@playwright/test";
import { unique } from "./helpers";

/**
 * The fork's error page (client_v2/src/routes/+error.svelte) and the reset it offers
 * (client_v2/src/lib/ng/viewState.ts).
 *
 * An unknown URL is the only one of the three failures this page covers that can be provoked
 * from the outside -- a failed `load` and a render-time exception both need broken code -- and it
 * renders exactly the same component, so it is what the assertions below drive.
 *
 * The 404 is produced by the CLIENT, not by the server: this build is a static SPA with a
 * `200.html` fallback, so the backend answers an unknown path with the app itself and the
 * SvelteKit router decides there is no route a moment later. That is why nothing here asserts on
 * an HTTP status; what matters is what ends up on screen.
 *
 * The path is suffixed per run so a cached or prerendered response for a fixed name cannot make
 * the test pass, or fail, for reasons of its own.
 */

const VIEW_KEY = "spoolman-v2-library-view";
const THEME_KEY = "spoolman-v2-theme";

const heading = (page: Page) => page.getByRole("heading", { name: "Something went wrong" });

/** A URL no route matches. One path segment, so the fallback's relative asset URLs still resolve. */
const nowhere = () => `/${unique("no-such-route")}`;

test("an unknown URL lands on the error page with the status it failed with", async ({ page }) => {
  await page.goto(nowhere(), { waitUntil: "networkidle" });

  await expect(heading(page)).toBeVisible();
  await expect(page.getByText("This page failed to render.")).toBeVisible();
  // Status and message together: the number alone does not say which failure this was, and the
  // message alone does not say whether the page was missing or broken.
  await expect(page.getByText(/^404 · /)).toBeVisible();
});

test("the reset clears the view state and nothing else, then reloads", async ({ page }) => {
  // Two full document loads rather than one: the reset is a real `location.reload()`, and a
  // client that boots the whole SPA twice does not fit the default per-test budget.
  test.slow();

  await page.goto(nowhere(), { waitUntil: "networkidle" });

  await page.evaluate(
    ([viewKey, themeKey]) => {
      localStorage.setItem(
        viewKey,
        JSON.stringify({ group: "location", sortKey: "name", sortAsc: true, showEmpty: true }),
      );
      localStorage.setItem(themeKey, "light");
    },
    [VIEW_KEY, THEME_KEY],
  );

  // Waiting on the document's own load event, not on a locator: the error page looks identical
  // before and after the reload, so only the navigation itself proves the button did anything.
  const reloaded = page.waitForEvent("load");
  await page.getByRole("button", { name: "Reset view settings & reload" }).click();
  await reloaded;

  // And it comes straight back, because the URL still matches no route.
  await expect(heading(page)).toBeVisible();

  expect(await page.evaluate((k) => localStorage.getItem(k), VIEW_KEY)).toBeNull();
  // The whole reason the reset is an allowlist rather than a `spoolman-v2-` sweep: a user who
  // pressed "reset view settings" did not ask to lose their theme.
  expect(await page.evaluate((k) => localStorage.getItem(k), THEME_KEY)).toBe("light");
});

test("the home link leads back to the library", async ({ page }) => {
  await page.goto(nowhere(), { waitUntil: "networkidle" });

  await page.getByRole("link", { name: "Go to home page" }).click();

  await expect(page).toHaveTitle("Library | Spoolman");
  await expect(heading(page)).toHaveCount(0);
});
