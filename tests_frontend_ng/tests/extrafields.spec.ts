import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { seedSpool, unique } from "./helpers";

/**
 * The three extra-field capabilities this fork's backend has and upstream's client did not
 * expose: a `location` entity, the `link` field type with its base-URL template (#129), and the
 * spool-only `copy_from_filament` flag (#118).
 *
 * Field DEFINITIONS are instance-wide -- one row in a server setting, not per test -- so every
 * definition made here is deleted in a `finally`. A leftover one would change what every later
 * spec in this suite and in the vendored one sees on a settings page, an inspector and an entity
 * form.
 *
 * The link field's expanded anchor takes two shapes. Read-only (the spool inspector mirrors its
 * parent filament's fields that way) the value itself is the link. Editable (the inspector edits a
 * spool's own fields in place) the box keeps the short value and an "open" icon beside it carries
 * the expanded URL, so the field stays clickable without an anchor doubling as a caret target.
 * Both are covered below.
 */

/** A field key that cannot collide with another run's, and is a legal key. */
const fieldKey = (prefix: string) => `${prefix}_${Date.now().toString(36)}`;

async function openFieldsManager(page: Page) {
  await page.goto("/settings", { waitUntil: "networkidle" });
  await expect(page.locator("#extra-fields")).toBeVisible();
}

/** The manager's entity tab strip, which is the only `.tabs` on the settings page. */
const entityTab = (page: Page, name: string) =>
  page.locator(".tabs").getByRole("button", { name, exact: true });

/** Definitions straight from the API, which is what the manager wrote to. */
async function definitions(api: APIRequestContext, entity: string) {
  const res = await api.get(`/api/v1/field/${entity}`);
  if (!res.ok()) throw new Error(`GET /field/${entity} -> ${res.status()} ${await res.text()}`);
  return (await res.json()) as {
    key: string;
    name: string;
    field_type: string;
    link_template?: string;
    copy_from_filament?: boolean;
  }[];
}

async function deleteField(api: APIRequestContext, entity: string, key: string) {
  await api.delete(`/api/v1/field/${entity}/${key}`);
}

test("a location field can be defined from the manager's own tab", async ({ page, request }) => {
  const key = fieldKey("loc_bin");
  const name = unique("Aisle");

  try {
    await openFieldsManager(page);
    await entityTab(page, "Location").click();

    await page.getByRole("button", { name: "Add Location field" }).click();
    await page.getByPlaceholder("lower_snake_case").fill(key);
    await page.getByPlaceholder("Display name").fill(name);
    await page.getByRole("button", { name: "Save field" }).click();

    // The editor closes and the definition joins the table on this tab.
    await expect(page.getByRole("button", { name: "Save field" })).toHaveCount(0);
    await expect(page.getByText(key, { exact: true })).toBeVisible();

    // And it really went to the location registry, not to the spool one the page opens on.
    expect((await definitions(request, "location")).map((f) => f.key)).toContain(key);
    expect((await definitions(request, "spool")).map((f) => f.key)).not.toContain(key);
  } finally {
    await deleteField(request, "location", key);
  }
});

test("a link field renders its value as the expanded template", async ({ page, request }) => {
  const key = fieldKey("product_page");
  const name = unique("Product page");
  const { spoolId, filamentId } = await seedSpool(request, "LinkFld", "Shelf L");

  try {
    await openFieldsManager(page);
    await entityTab(page, "Filament").click();
    await page.getByRole("button", { name: "Add Filament field" }).click();

    // The template box belongs to the link type alone, so it is not offered until the type is.
    await expect(page.getByLabel("Link URL")).toHaveCount(0);

    await page.getByPlaceholder("lower_snake_case").fill(key);
    await page.getByPlaceholder("Display name").fill(name);
    await page.getByRole("combobox", { name: "Type" }).selectOption("link");
    await page.getByLabel("Link URL").fill("https://example.invalid/dp/{}");
    await page.getByRole("button", { name: "Save field" }).click();
    await expect(page.getByRole("button", { name: "Save field" })).toHaveCount(0);

    const saved = (await definitions(request, "filament")).find((f) => f.key === key);
    expect(saved?.field_type).toBe("link");
    expect(saved?.link_template).toBe("https://example.invalid/dp/{}");

    // Give the filament a value for it. Only the short code is stored; the URL is the
    // definition's business.
    const res = await request.patch(`/api/v1/filament/${filamentId}`, {
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ extra: { [key]: JSON.stringify("B0ABC") } }),
    });
    expect(res.ok()).toBeTruthy();

    // The spool inspector mirrors its filament's fields read-only, which is where a link field
    // is a link rather than an editable value.
    await page.goto(`/?sel=spool:${spoolId}`, { waitUntil: "networkidle" });
    const link = page.getByRole("link", { name: "B0ABC", exact: true });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "https://example.invalid/dp/B0ABC");
    await expect(link).toHaveAttribute("target", "_blank");
  } finally {
    await deleteField(request, "filament", key);
  }
});

test("an editable spool link field offers its expanded URL beside the box", async ({ page, request }) => {
  const key = fieldKey("listing");
  const { spoolId } = await seedSpool(request, "LinkSpool", "Shelf S");

  try {
    // Defined straight through the API: the manager's own link flow is covered above, and this
    // case is about how the value renders where it is edited.
    const def = await request.post(`/api/v1/field/spool/${key}`, {
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({
        name: unique("Listing"),
        order: 0,
        field_type: "link",
        link_template: "https://example.invalid/item/{}",
      }),
    });
    expect(def.ok()).toBeTruthy();

    const res = await request.patch(`/api/v1/spool/${spoolId}`, {
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ extra: { [key]: JSON.stringify("X 1/2&3") } }),
    });
    expect(res.ok()).toBeTruthy();

    await page.goto(`/?sel=spool:${spoolId}`, { waitUntil: "networkidle" });
    // The value stays editable text, so it is a textbox and not a link ...
    await expect(page.getByRole("textbox", { name: /^Listing/ })).toHaveValue("X 1/2&3");
    // ... and the expanded, URL-encoded template rides beside it as the open icon.
    const open = page.getByRole("link", { name: /^Open https:\/\/example\.invalid\/item\// });
    await expect(open).toBeVisible();
    await expect(open).toHaveAttribute("href", "https://example.invalid/item/X%201%2F2%263");
    await expect(open).toHaveAttribute("target", "_blank");
  } finally {
    await deleteField(request, "spool", key);
  }
});

test("copy from filament is offered for spool fields only", async ({ page }) => {
  await openFieldsManager(page);

  // Spools are the tab the page opens on, and the only entity that has a parent filament to
  // inherit from.
  await page.getByRole("button", { name: "Add Spool field" }).click();
  await expect(page.getByLabel("Copy from Filament")).toBeVisible();

  // Switching tabs puts the editor away; the filament editor has no such control.
  await entityTab(page, "Filament").click();
  await page.getByRole("button", { name: "Add Filament field" }).click();
  await expect(page.getByRole("button", { name: "Save field" })).toBeVisible();
  await expect(page.getByLabel("Copy from Filament")).toHaveCount(0);
});
