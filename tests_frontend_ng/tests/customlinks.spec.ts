import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { seedSpool, unique } from "./helpers";

/**
 * Custom links (#413): operator-configured entries in the nav, and per-spool action buttons
 * whose URL is a template over the spool's fields.
 *
 * Both lists are edited on the settings page and read wherever they show. The oracle for the
 * template is the rendered `href`: the substitution is computed by hand here, never by the
 * code under test.
 */

async function setSetting(request: APIRequestContext, key: string, value: unknown) {
  const res = await request.post(`/api/v1/setting/${key}`, {
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify(JSON.stringify(value)),
  });
  if (!res.ok()) throw new Error(`setting ${key} -> ${res.status()} ${await res.text()}`);
}

async function stored(request: APIRequestContext, key: string) {
  const res = await request.get(`/api/v1/setting/${key}`);
  return JSON.parse(((await res.json()) as { value: string }).value) as unknown;
}

const navPanel = (page: Page) => page.getByRole("region", { name: "Navigation links" });
const actionsPanel = (page: Page) => page.getByRole("region", { name: "Spool actions" });

async function addLink(page: Page, panel: ReturnType<typeof navPanel>, name: string, url: string) {
  await panel.getByRole("button", { name: "Add link" }).click();
  const dialog = page.getByRole("dialog", { name: "Add link" });
  await dialog.getByRole("textbox", { name: "Name" }).fill(name);
  // The URL field is announced by the list's own label: "URL" for the nav, "URL Template"
  // for the spool actions.
  await dialog.getByRole("textbox", { name: /^URL/ }).fill(url);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeHidden();
}

test.beforeEach(async ({ request }) => {
  await setSetting(request, "custom_links", []);
  await setSetting(request, "spool_action_links", []);
});

test.afterAll(async ({ request }) => {
  await setSetting(request, "custom_links", []);
  await setSetting(request, "spool_action_links", []);
});

test("with nothing configured the nav has no extra entries", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  await expect(page.locator("nav a[target=_blank]")).toHaveCount(0);
});

test("a nav link can be added, appears in the nav at once, be edited, and removed", async ({
  page,
  request,
}) => {
  const name = unique("Mainsail");
  await page.goto("/settings", { waitUntil: "networkidle" });
  await addLink(page, navPanel(page), name, "http://mainsail.local");

  // In the nav without a reload, as an external link in a new tab.
  const link = page.getByRole("link", { name, exact: true }).first();
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", "http://mainsail.local");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", /noopener/);
  expect(await stored(request, "custom_links")).toEqual([{ name, url: "http://mainsail.local" }]);

  // Edit it.
  await navPanel(page)
    .getByRole("button", { name: `Edit: ${name}` })
    .click();
  const edit = page.getByRole("dialog", { name: "Edit link" });
  await expect(edit.getByRole("textbox", { name: "Name" })).toHaveValue(name);
  await edit.getByRole("textbox", { name: /^URL/ }).fill("http://fluidd.local");
  await edit.getByRole("button", { name: "Save" }).click();
  await expect(edit).toBeHidden();
  await expect(page.getByRole("link", { name, exact: true }).first()).toHaveAttribute(
    "href",
    "http://fluidd.local",
  );

  // Remove it, through the confirmation.
  await navPanel(page)
    .getByRole("button", { name: `Delete: ${name}` })
    .click();
  const confirm = page.getByRole("dialog");
  await expect(confirm).toContainText(name);
  await confirm.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("link", { name, exact: true })).toHaveCount(0);
  expect(await stored(request, "custom_links")).toEqual([]);
});

test("the form refuses an empty name or URL rather than storing a blank entry", async ({
  page,
  request,
}) => {
  await page.goto("/settings", { waitUntil: "networkidle" });
  await navPanel(page).getByRole("button", { name: "Add link" }).click();
  const dialog = page.getByRole("dialog", { name: "Add link" });
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("textbox", { name: "Name" })).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await dialog.getByRole("button", { name: "Cancel" }).click();
  expect(await stored(request, "custom_links")).toEqual([]);
});

test("a spool action opens a URL with the spool's own fields substituted", async ({
  page,
  request,
}) => {
  const location = unique("Rack A");
  const { spoolId } = await seedSpool(request, "Action", location);
  const name = unique("Load");

  await page.goto("/settings", { waitUntil: "networkidle" });
  await addLink(
    page,
    actionsPanel(page),
    name,
    "http://moonraker.local/server/spoolman/spool_id?id={id}&loc={location}&nope={unknown}",
  );
  expect(await stored(request, "spool_action_links")).toHaveLength(1);

  await page.goto(`/?sel=spool:${spoolId}`, { waitUntil: "networkidle" });
  const action = page
    .getByRole("group", { name: "Actions" })
    .getByRole("link", { name, exact: true });
  await expect(action).toBeVisible();
  // Computed by hand: the id verbatim, the location URL-encoded, the unknown token dropped.
  await expect(action).toHaveAttribute(
    "href",
    `http://moonraker.local/server/spoolman/spool_id?id=${spoolId}&loc=${encodeURIComponent(location)}&nope=`,
  );
  await expect(action).toHaveAttribute("target", "_blank");
});

test("the settings panels are absent for a spool with no actions configured", async ({
  page,
  request,
}) => {
  const { spoolId } = await seedSpool(request, "NoAction", unique("Rack B"));
  await page.goto(`/?sel=spool:${spoolId}`, { waitUntil: "networkidle" });
  await expect(page.getByRole("group", { name: "Actions" })).toHaveCount(0);
});
