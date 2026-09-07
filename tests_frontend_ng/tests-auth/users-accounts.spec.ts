import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * The account-management panel (client_v2/src/lib/ng/components/UserSettings.svelte, #413),
 * and what a read-only account does NOT get to see.
 *
 * Runs on the accounts instance -- see the `auth-accounts` project in playwright.config.ts.
 * It shares that instance with accounts.spec.ts: the first account either spec seeds flips
 * accounts_enabled for good, which is fine here because every test below logs in through the
 * UI as an administrator it seeded itself.
 *
 * The oracles are the server's: the user list over the API after each change, and a real
 * `POST /auth/login` with the password that was just set.
 */

const TOKEN = process.env.SPOOLMAN_AUTH_TOKEN ?? "spoolman-e2e-token";

const auth = { Authorization: `Bearer ${TOKEN}` };

async function usersOnServer(request: APIRequestContext) {
  const res = await request.get("/api/v1/auth/users", { headers: auth });
  return (await res.json()) as { id: number; username: string; role: string }[];
}

async function seedUser(
  request: APIRequestContext,
  username: string,
  password: string,
  role: "admin" | "readonly",
) {
  const res = await request.post("/api/v1/auth/users", {
    headers: auth,
    data: { username, password, role },
  });
  expect(res.ok(), `could not seed ${username}: ${res.status()}`).toBeTruthy();
}

async function loginViaUi(page: Page, username: string, password: string) {
  await page.goto("/");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.locator("input[autocomplete=username]").fill(username);
  await dialog.locator("input[autocomplete=current-password]").fill(password);
  await dialog.getByRole("button", { name: /^log in$/i }).click();
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("dialog")).toBeHidden();
}

const panel = (page: Page) => page.getByRole("region", { name: "Users" });

test.describe("as an administrator", () => {
  const admin = `admin-${Date.now()}`;
  const adminPassword = "correct-horse-413";

  test.beforeAll(async ({ request }) => {
    await seedUser(request, admin, adminPassword, "admin");
  });

  test.beforeEach(async ({ page }) => {
    await loginViaUi(page, admin, adminPassword);
    await page.goto("/settings", { waitUntil: "networkidle" });
  });

  test("lists the accounts and marks the one signed in", async ({ page }) => {
    const row = panel(page).locator("li", { hasText: admin });
    await expect(row).toBeVisible();
    await expect(row).toContainText("(you)");
    await expect(row.getByRole("combobox", { name: `Role: ${admin}` })).toHaveValue("admin");
  });

  test("creates a read-only account, changes its role after confirming, and deletes it", async ({
    page,
    request,
  }) => {
    const username = `ro-${Date.now()}`;

    // Create.
    await panel(page).getByRole("textbox", { name: "Username" }).fill(username);
    await panel(page).getByRole("textbox", { name: "Password" }).fill("first-pw");
    await panel(page).getByRole("combobox", { name: "Role", exact: true }).selectOption("readonly");
    await panel(page).getByRole("button", { name: "Add user" }).click();
    const row = panel(page).locator("li", { hasText: username });
    await expect(row).toBeVisible();
    expect((await usersOnServer(request)).find((u) => u.username === username)?.role).toBe(
      "readonly",
    );

    // The role change asks first, and cancelling keeps the server's value.
    const role = row.getByRole("combobox", { name: `Role: ${username}` });
    await role.selectOption("admin");
    const confirm = page.getByRole("dialog", { name: "Change role" });
    await expect(confirm).toContainText(username);
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(confirm).toBeHidden();
    // The control goes back to what was never changed; a select left on "admin" would be lying.
    await expect(role).toHaveValue("readonly");
    expect((await usersOnServer(request)).find((u) => u.username === username)?.role).toBe(
      "readonly",
    );

    await role.selectOption("admin");
    await page
      .getByRole("dialog", { name: "Change role" })
      .getByRole("button", { name: "Change role" })
      .click();
    await expect
      .poll(async () => (await usersOnServer(request)).find((u) => u.username === username)?.role)
      .toBe("admin");

    // Delete, through the confirmation.
    await row.getByRole("button", { name: `Delete: ${username}` }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
    await expect(row).toHaveCount(0);
    expect((await usersOnServer(request)).map((u) => u.username)).not.toContain(username);
  });

  test("resets a password, and the new one logs in", async ({ page, request }) => {
    const username = `reset-${Date.now()}`;
    await seedUser(request, username, "old-pw", "readonly");
    await page.reload({ waitUntil: "networkidle" });

    await panel(page)
      .locator("li", { hasText: username })
      .getByRole("button", { name: `Reset password: ${username}` })
      .click();
    const dialog = page.getByRole("dialog", {
      name: `Reset password for ${username}`,
    });
    await dialog.locator("input[type=password]").fill("new-pw-413");
    await dialog.getByRole("button", { name: "Reset password" }).click();
    await expect(dialog).toBeHidden();

    const oldLogin = await request.post("/api/v1/auth/login", {
      data: { username, password: "old-pw" },
    });
    expect(oldLogin.status()).toBe(401);
    const newLogin = await request.post("/api/v1/auth/login", {
      data: { username, password: "new-pw-413" },
    });
    expect(newLogin.ok()).toBeTruthy();
  });

  test("surfaces the server's refusal rather than second-guessing it", async ({
    page,
    request,
  }) => {
    // A duplicate username is the backend's call (409), and its wording is what the user
    // should read.
    await panel(page).getByRole("textbox", { name: "Username" }).fill(admin);
    await panel(page).getByRole("textbox", { name: "Password" }).fill("whatever");
    await panel(page).getByRole("button", { name: "Add user" }).click();
    await expect(panel(page).getByRole("alert")).toContainText("already exists");
    expect((await usersOnServer(request)).filter((u) => u.username === admin)).toHaveLength(1);
  });
});

test.describe("as a read-only account", () => {
  const reader = `reader-${Date.now()}`;
  const readerPassword = "look-dont-touch";

  test.beforeAll(async ({ request }) => {
    await seedUser(request, reader, readerPassword, "readonly");
  });

  test("sees none of the operator panels on the settings page", async ({ page }) => {
    await loginViaUi(page, reader, readerPassword);
    await page.goto("/settings", { waitUntil: "networkidle" });

    // Upstream's own controls are still there, so the page did load.
    await expect(page.getByLabel("Currency")).toBeVisible();

    for (const name of ["Users", "Printers", "Navigation links", "Spool actions", "AI"]) {
      await expect(page.getByRole("region", { name })).toHaveCount(0);
    }
    await expect(page.getByRole("switch", { name: "Scale large units" })).toHaveCount(0);
  });
});
