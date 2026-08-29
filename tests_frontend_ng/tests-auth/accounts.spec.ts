import { expect, test, type Page } from "@playwright/test";

/**
 * The Svelte client against a backend with a user account (#406).
 *
 * Its own instance -- see the `auth-accounts` project in playwright.config.ts. Seeding an account
 * is a one-way door: the backend refuses to delete the last administrator, so accounts_enabled
 * can never go back to false. Sharing an instance with token.spec.ts would therefore break that
 * file on the second run and on any CI retry.
 */

const TOKEN = process.env.SPOOLMAN_AUTH_TOKEN ?? "spoolman-e2e-token";

function apiRequests(page: Page): string[] {
  const seen: string[] = [];
  page.on("response", (r) => {
    const url = new URL(r.url());
    if (url.pathname.startsWith("/api/v1")) seen.push(`${r.status()} ${url.pathname}`);
  });
  return seen;
}

test.describe("with a user account", () => {
  const username = `e2e-${Date.now()}`;
  const password = "correct-horse-406";

  test.beforeAll(async ({ request }) => {
    // Bootstrapped with the static token, which authenticates as an administrator. Creating
    // any account flips accounts_enabled, which is what makes the dialog offer a login form.
    const res = await request.post("/api/v1/auth/users", {
      headers: { Authorization: `Bearer ${TOKEN}` },
      data: { username, password, role: "admin" },
    });
    expect(res.ok(), `could not seed the account: ${res.status()}`).toBeTruthy();
  });

  test("offers a login form, rejects a wrong password, accepts the right one", async ({ page }) => {
    await page.goto("/");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("#login-title")).toHaveText(/log in/i);

    await dialog.locator("input[autocomplete=username]").fill(username);
    await dialog.locator("input[autocomplete=current-password]").fill("wrong");
    await dialog.getByRole("button", { name: /^log in$/i }).click();

    // The reason has to stay next to the form; a toast would vanish before it was read.
    await expect(dialog.getByRole("alert")).toBeVisible();
    await expect(dialog).toBeVisible();

    const seen = apiRequests(page);
    await dialog.locator("input[autocomplete=current-password]").fill(password);
    await dialog.getByRole("button", { name: /^log in$/i }).click();

    // A correct login reloads the page; let it land before measuring.
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect
      .poll(() => seen.filter((s) => s.startsWith("200")).length, { timeout: 15_000 })
      .toBeGreaterThan(0);
    expect(seen.filter((s) => s.startsWith("401") && !s.includes("/auth/login"))).toEqual([]);
  });
});
