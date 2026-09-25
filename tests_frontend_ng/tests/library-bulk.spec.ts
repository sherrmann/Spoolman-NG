import { expect, test, type Page } from "@playwright/test";
import { seedFilament, spoolById, unique } from "./helpers";

/**
 * Selecting several spools in the Library and editing or archiving them together (#412, step 1).
 *
 * Upstream's Library selects one spool at a time through the URL; the selection layer is this
 * fork's, reaching every spool row through an import seam (see
 * docs/upstream/client-v2-fork-additions.md). What matters most is that with selection off the
 * Library is upstream's DOM, untouched: upstream's own suite finds rows by their link role.
 */

async function seedThree(request: Parameters<typeof seedFilament>[0]) {
  const location = unique("BulkShelf");
  const filament = await seedFilament(request, "Bulk");
  const ids: number[] = [];
  for (let i = 0; i < 3; i++) {
    const res = await request.post("/api/v1/spool", {
      // Drawn from, and by different amounts: identical never-used spools collapse into one
      // pile row in the grouped view, which has no per-spool checkbox until it is expanded.
      data: { filament_id: filament.id, location, used_weight: 10 * (i + 1) },
    });
    expect(res.ok()).toBeTruthy();
    ids.push(((await res.json()) as { id: number }).id);
  }
  return { location, filament, ids };
}

/** The flat Library narrowed to one location, so the shared instance's other spools stay out. */
async function openAt(page: Page, location: string, extra = "") {
  await page.goto(
    `/?group=none&f=location%3A${encodeURIComponent(location)}${extra}`,
    {
      waitUntil: "networkidle",
    },
  );
}

const bar = (page: Page) => page.getByRole("region", { name: /selected/ });

test("with selection off the library is upstream's: no checkboxes, and a row still opens its spool", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedThree(request);
  await openAt(page, location);

  await expect(page.locator("a.row", { hasText: `#${ids[0]}` })).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await page.locator("a.row", { hasText: `#${ids[0]}` }).click();
  await expect(page).toHaveURL(new RegExp(`sel=spool(%3A|:)${ids[0]}`));
});

test("bulk edit moves exactly the ticked spools", async ({ page, request }) => {
  const { location, ids } = await seedThree(request);
  const target = unique("BulkTarget");
  await openAt(page, location);

  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("checkbox", { name: `Select spool #${ids[0]}` }).check();
  await page.getByRole("checkbox", { name: `Select spool #${ids[1]}` }).check();
  await expect(bar(page)).toContainText("2 selected");

  await bar(page).getByRole("button", { name: "Edit" }).click();
  await page
    .getByRole("dialog")
    .getByRole("combobox", { name: "Location" })
    .fill(target);
  await page.getByRole("dialog").getByRole("button", { name: "Apply" }).click();

  await expect
    .poll(async () => (await spoolById(request, ids[0])).location)
    .toBe(target);
  await expect
    .poll(async () => (await spoolById(request, ids[1])).location)
    .toBe(target);
  expect((await spoolById(request, ids[2])).location).toBe(location);
  // A successful apply clears the selection.
  await expect(bar(page)).toHaveCount(0);
});

test("bulk edit with nothing ticked says so and changes nothing", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedThree(request);
  await openAt(page, location);

  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("checkbox", { name: `Select spool #${ids[0]}` }).check();
  await bar(page).getByRole("button", { name: "Edit" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Apply" }).click();

  await expect(page.getByRole("dialog").getByRole("alert")).toHaveText(
    "Tick at least one field to change.",
  );
  expect((await spoolById(request, ids[0])).location).toBe(location);
});

test("archive the selection, then unarchive it from the archived view", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedThree(request);
  const archived = async (id: number) =>
    (
      (await (await request.get(`/api/v1/spool/${id}`)).json()) as {
        archived: boolean;
      }
    ).archived;
  await openAt(page, location);

  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("checkbox", { name: `Select spool #${ids[0]}` }).check();
  await page.getByRole("checkbox", { name: `Select spool #${ids[1]}` }).check();
  // Nothing archived is selected, so there is nothing to unarchive.
  await expect(
    bar(page).getByRole("button", { name: "Unarchive", exact: true }),
  ).toHaveCount(0);
  await bar(page).getByRole("button", { name: "Archive", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Archive", exact: true })
    .click();

  await expect.poll(() => archived(ids[0])).toBe(true);
  await expect.poll(() => archived(ids[1])).toBe(true);
  expect(await archived(ids[2])).toBe(false);

  await openAt(page, location, "&arch=1");
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("checkbox", { name: `Select spool #${ids[0]}` }).check();
  await page.getByRole("checkbox", { name: `Select spool #${ids[2]}` }).check();
  // A mixed selection is ordinary with archived spools listed: both actions are offered.
  await expect(
    bar(page).getByRole("button", { name: "Archive", exact: true }),
  ).toBeVisible();
  await bar(page)
    .getByRole("button", { name: "Unarchive", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Unarchive", exact: true })
    .click();

  await expect.poll(() => archived(ids[0])).toBe(false);
  // Unarchive applies to the archived spools only; the active one was never touched.
  expect(await archived(ids[2])).toBe(false);
  expect(await archived(ids[1])).toBe(true);
});

test("select all shown, clear, and turning the mode off", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedThree(request);
  await openAt(page, location);

  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("button", { name: "Select all shown" }).click();
  await expect(bar(page)).toContainText(`${ids.length} selected`);

  await bar(page).getByRole("button", { name: "Clear selection" }).click();
  await expect(bar(page)).toHaveCount(0);

  await page.getByRole("checkbox", { name: `Select spool #${ids[0]}` }).check();
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await expect(bar(page)).toHaveCount(0);
});

test("grouped by filament, the checkboxes sit under the group header", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedThree(request);
  await page.goto(
    `/?group=filament&f=location%3A${encodeURIComponent(location)}`,
    {
      waitUntil: "networkidle",
    },
  );

  await page.getByRole("button", { name: "Select", exact: true }).click();
  for (const id of ids)
    await expect(
      page.getByRole("checkbox", { name: `Select spool #${id}` }),
    ).toBeVisible();
});
