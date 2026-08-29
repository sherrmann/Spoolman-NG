import { expect, test, type Page, type Request } from "@playwright/test";

/**
 * The Svelte client against a backend with a shared API token and no user accounts (#406).
 *
 * Its own instance, started with SPOOLMAN_API_TOKEN and no accounts -- see the `auth-token`
 * project in playwright.config.ts. The rest of the suite shares one backend with auth switched
 * off, and turning it on there would answer 401 to every other spec.
 *
 * Separate from accounts.spec.ts, and not merely a separate describe: creating an account flips
 * accounts_enabled permanently (the backend refuses to delete the last administrator), which
 * would turn the token field asserted below into a login form for every later run and every
 * CI retry.
 *
 * The regression being guarded is specific: the client used to send no credential at all, so
 * every request was refused, and its only answer to a 401 was to reload -- which nothing about
 * a token can fix. The tab reloaded every 30 seconds forever and never asked for the token it
 * was missing.
 */

const TOKEN = process.env.SPOOLMAN_AUTH_TOKEN ?? "spoolman-e2e-token";

// No "sign out" helper here on purpose. Playwright gives every test its own browser context,
// so localStorage already starts empty and each test begins from "refused" for free. An
// addInitScript that cleared the token would run again on *every* navigation, including the
// reload that accepting a credential triggers -- wiping the token mid-test and making the app
// look broken when it is not.

function apiRequests(page: Page): string[] {
  const seen: string[] = [];
  page.on("response", (r) => {
    const url = new URL(r.url());
    if (url.pathname.startsWith("/api/v1")) seen.push(`${r.status()} ${url.pathname}`);
  });
  return seen;
}

test.describe("with a shared API token", () => {
  test("asks for the token instead of reloading forever", async ({ page }) => {
    const seen = apiRequests(page);
    await page.goto("/");

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // accounts_enabled is false on this instance, so it must offer the token field.
    await expect(dialog.locator("#login-title")).toHaveText(/API token/i);

    // The bug was an endless reload. A handful of concurrent 401s on first paint is
    // expected; a loop is not, so give it time to misbehave and then bound it.
    await page.waitForTimeout(3000);
    expect(seen.filter((s) => s.startsWith("401")).length).toBeLessThan(40);
    await expect(dialog).toBeVisible();
  });

  test("accepts the token, and the app then loads", async ({ page }) => {
    await page.goto("/");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    await dialog.locator("input[type=password]").fill(TOKEN);
    // Everything before this point was the unauthenticated load; the click reloads the page.
    const seen = apiRequests(page);
    await dialog.getByRole("button", { name: /save token/i }).click();

    // Accepting reloads the page. Let that land before judging what went out, or we measure
    // the outgoing page rather than the reloaded one.
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect
      .poll(() => seen.filter((s) => s.startsWith("200")).length, { timeout: 15_000 })
      .toBeGreaterThan(0);
    expect(seen.filter((s) => s.startsWith("401"))).toEqual([]);
  });

  test("carries the token on the websocket handshake", async ({ page }) => {
    // Browsers cannot set headers on a WS upgrade, so the token has to be in the URL or live
    // updates are refused while the rest of the app looks fine.
    await page.goto("/");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const sockets: string[] = [];
    page.on("websocket", (ws) => sockets.push(ws.url()));

    await dialog.locator("input[type=password]").fill(TOKEN);
    await dialog.getByRole("button", { name: /save token/i }).click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("dialog")).toBeHidden();

    // Live sync opens its sockets once the reloaded app has booted, so this trails the
    // REST calls by a moment.
    await expect
      .poll(() => sockets.filter((u) => u.includes(`token=${TOKEN}`)).length, { timeout: 15_000 })
      .toBeGreaterThan(0);
  });

  test("sends the credential on every REST call, not just the first", async ({ page }) => {
    const unauthenticated: string[] = [];
    page.on("request", (req: Request) => {
      const url = new URL(req.url());
      if (!url.pathname.startsWith("/api/v1")) return;
      // /auth/status and /auth/login are open routes and legitimately go out bare.
      if (url.pathname.includes("/auth/")) return;
      if (!req.headers()["authorization"]) unauthenticated.push(url.pathname);
    });

    await page.goto("/");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.locator("input[type=password]").fill(TOKEN);
    await dialog.getByRole("button", { name: /save token/i }).click();
    await expect(page.getByRole("dialog")).toBeHidden();

    // Only the pre-credential load may appear here. Anything after the reload means a call
    // site was missed -- which is exactly how the AI endpoints were nearly left behind.
    unauthenticated.length = 0;
    await page.reload();
    await page.waitForLoadState("networkidle");
    expect(unauthenticated).toEqual([]);
  });
});
