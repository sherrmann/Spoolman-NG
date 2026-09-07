import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { seedFilament, seedSpool, unique } from "./helpers";

/**
 * Printers (#75 / #413): the registry on the settings page, the picker in the add-spool form,
 * and the assignment field in the spool inspector.
 *
 * The picker and the field appear only once a printer exists, so the first test pins their
 * absence and the rest create printers through the UI and check the assignment on the server,
 * which is the oracle: `GET /spool/{id}` carries the nested printer.
 *
 * Every printer made here is deleted again at the end. The database is shared with the other
 * specs, and a leftover printer would put a field into forms they do not expect.
 */

const panel = (page: Page) => page.getByRole("region", { name: "Printers" });

async function printersOnServer(request: APIRequestContext) {
  return (await (await request.get("/api/v1/printer")).json()) as {
    id: number;
    name: string;
  }[];
}

async function spoolPrinter(request: APIRequestContext, spoolId: number) {
  const spool = (await (await request.get(`/api/v1/spool/${spoolId}`)).json()) as {
    printer?: { id: number; name: string };
  };
  return spool.printer?.name;
}

async function deleteAllPrinters(request: APIRequestContext) {
  for (const p of await printersOnServer(request)) await request.delete(`/api/v1/printer/${p.id}`);
}

async function addPrinter(page: Page, name: string, comment = "") {
  await panel(page).getByRole("button", { name: "Add printer" }).click();
  const dialog = page.getByRole("dialog", { name: "Add printer" });
  await dialog.getByRole("textbox", { name: "Name" }).fill(name);
  if (comment) await dialog.getByRole("textbox", { name: "Comment" }).fill(comment);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeHidden();
}

test.beforeEach(async ({ request }) => {
  await deleteAllPrinters(request);
});

test.afterAll(async ({ request }) => {
  await deleteAllPrinters(request);
});

test("with no printers, neither the add form nor the inspector offers a printer field", async ({
  page,
  request,
}) => {
  const { spoolId } = await seedSpool(request, "NoPrinter", unique("Bench"));
  await page.goto(`/?sel=spool:${spoolId}`, { waitUntil: "networkidle" });
  await expect(page.getByRole("combobox", { name: "Printer", exact: true })).toHaveCount(0);

  await page
    .locator("header")
    .getByRole("button", { name: "Add spools" })
    .locator("visible=true")
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("combobox", { name: /^Printer/ })).toHaveCount(0);
});

test("a printer can be added, edited and deleted from the settings page", async ({
  page,
  request,
}) => {
  const name = unique("Voron");
  await page.goto("/settings", { waitUntil: "networkidle" });
  await expect(panel(page)).toContainText("No printers yet");

  await addPrinter(page, name, "left bench");
  await expect(panel(page)).toContainText(name);
  await expect(panel(page)).toContainText("left bench");
  expect((await printersOnServer(request)).map((p) => p.name)).toContain(name);

  await panel(page)
    .getByRole("button", { name: `Edit: ${name}` })
    .click();
  const edit = page.getByRole("dialog", { name: "Edit printer" });
  await expect(edit.getByRole("textbox", { name: "Comment" })).toHaveValue("left bench");
  await edit.getByRole("textbox", { name: "Comment" }).fill("");
  await edit.getByRole("button", { name: "Save" }).click();
  await expect(edit).toBeHidden();
  await expect(panel(page)).not.toContainText("left bench");

  await panel(page)
    .getByRole("button", { name: `Delete: ${name}` })
    .click();
  const confirm = page.getByRole("dialog");
  await expect(confirm).toContainText("unassigned, not deleted");
  await confirm.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(panel(page)).not.toContainText(name);
  expect((await printersOnServer(request)).map((p) => p.name)).not.toContain(name);
});

test("the form refuses a blank name", async ({ page, request }) => {
  await page.goto("/settings", { waitUntil: "networkidle" });
  await panel(page).getByRole("button", { name: "Add printer" }).click();
  const dialog = page.getByRole("dialog", { name: "Add printer" });
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("textbox", { name: "Name" })).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await dialog.getByRole("button", { name: "Cancel" }).click();
  expect(await printersOnServer(request)).toEqual([]);
});

test("a new spool can be assigned to a printer from the add form", async ({ page, request }) => {
  const printer = unique("Prusa");
  const filament = await seedFilament(request, "Assign");
  await page.goto("/settings", { waitUntil: "networkidle" });
  await addPrinter(page, printer);

  await page.goto("/", { waitUntil: "networkidle" });
  await page
    .locator("header")
    .getByRole("button", { name: "Add spools" })
    .locator("visible=true")
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox").first().fill(filament.name);
  await dialog.getByRole("button", { name: filament.name }).first().click();

  // The picker is a plain <label> around a <select>, whose name includes its hint.
  await dialog.getByRole("combobox", { name: /^Printer/ }).selectOption({ label: printer });
  await dialog.getByRole("button", { name: "Add 1 spool", exact: true }).click();
  await expect(dialog).toBeHidden();

  const spools = (await (await request.get(`/api/v1/spool?filament_id=${filament.id}`)).json()) as {
    id: number;
  }[];
  expect(spools).toHaveLength(1);
  expect(await spoolPrinter(request, spools[0].id)).toBe(printer);
});

test("the inspector shows the assignment and can change or clear it", async ({ page, request }) => {
  const a = unique("Bambu");
  const b = unique("Ender");
  await page.goto("/settings", { waitUntil: "networkidle" });
  await addPrinter(page, a);
  await addPrinter(page, b);
  const { spoolId } = await seedSpool(request, "Inspect", unique("Bench"));

  await page.goto(`/?sel=spool:${spoolId}`, { waitUntil: "networkidle" });
  const field = page.getByRole("combobox", { name: "Printer", exact: true });
  await expect(field).toBeVisible();
  await expect(field).toHaveValue("");

  await field.selectOption({ label: a });
  await expect.poll(() => spoolPrinter(request, spoolId)).toBe(a);

  // The choice survives a reload: it is read back from the server, not remembered locally.
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.getByRole("combobox", { name: "Printer", exact: true })).toHaveValue(
    String((await printersOnServer(request)).find((p) => p.name === a)?.id),
  );

  await page.getByRole("combobox", { name: "Printer", exact: true }).selectOption({ label: b });
  await expect.poll(() => spoolPrinter(request, spoolId)).toBe(b);

  await page
    .getByRole("combobox", { name: "Printer", exact: true })
    .selectOption({ label: "Not assigned" });
  await expect.poll(() => spoolPrinter(request, spoolId)).toBeUndefined();
});

test("deleting a printer unassigns its spools rather than deleting them", async ({
  page,
  request,
}) => {
  const name = unique("Retired");
  await page.goto("/settings", { waitUntil: "networkidle" });
  await addPrinter(page, name);
  const printerId = (await printersOnServer(request)).find((p) => p.name === name)!.id;
  const { spoolId } = await seedSpool(request, "Orphan", unique("Bench"));
  await request.patch(`/api/v1/spool/${spoolId}`, {
    data: { printer_id: printerId },
  });
  expect(await spoolPrinter(request, spoolId)).toBe(name);

  await page.goto("/settings", { waitUntil: "networkidle" });
  // The spool count is what tells you a delete will touch something.
  await expect(panel(page).locator("li", { hasText: name })).toContainText("1");
  await panel(page)
    .getByRole("button", { name: `Delete: ${name}` })
    .click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
  await expect(panel(page)).not.toContainText(name);

  expect(await spoolPrinter(request, spoolId)).toBeUndefined();
  expect((await request.get(`/api/v1/spool/${spoolId}`)).ok()).toBe(true);
});
