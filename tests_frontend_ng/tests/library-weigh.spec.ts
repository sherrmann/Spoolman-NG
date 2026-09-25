import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { seedFilament, unique } from "./helpers";

/**
 * Weighing several selected spools in a row from the Library (#412, step 2).
 *
 * Builds on the selection layer tested in library-bulk.spec.ts: "Weigh in" opens a modal that
 * steps through the selection in order, recording either a consumed length/weight or a measured
 * gross weight per spool through the same calls the inspector's Adjust panel makes.
 */

/** The spool's remaining weight straight from the API, since helpers.ts's spoolById does not
 * carry that field. */
async function remainingWeightOf(
  request: APIRequestContext,
  spoolId: number,
): Promise<number> {
  const res = await request.get(`/api/v1/spool/${spoolId}`);
  const spool = (await res.json()) as { remaining_weight: number };
  return spool.remaining_weight;
}

/** Every seeded filament here is 1000 g of filament on a 190 g spool, so a gross weight of
 * `g` measures out to `g - 190` remaining, independent of the app's own calculation. */
function remainingFor(gross: number): number {
  return gross - 190;
}

/** The flat Library narrowed to one location, so the shared instance's other spools stay out. */
async function openAt(page: Page, location: string) {
  await page.goto(`/?group=none&f=location%3A${encodeURIComponent(location)}`, {
    waitUntil: "networkidle",
  });
}

const bar = (page: Page) => page.getByRole("region", { name: /selected/ });
const dialog = (page: Page) =>
  page.getByRole("dialog", { name: "Weigh Spools" });

async function seedTwo(request: Parameters<typeof seedFilament>[0]) {
  const location = unique("WeighShelf");
  const filament = await seedFilament(request, "Weigh");
  const ids: number[] = [];
  for (let i = 0; i < 2; i++) {
    const res = await request.post("/api/v1/spool", {
      // Drawn from by different amounts, like the bulk spec: identical never-used spools
      // collapse into one pile row with no per-spool checkbox until expanded.
      data: { filament_id: filament.id, location, used_weight: 10 * (i + 1) },
    });
    expect(res.ok()).toBeTruthy();
    ids.push(((await res.json()) as { id: number }).id);
  }
  return { location, filament, ids };
}

async function selectAndOpenWeighIn(page: Page, ids: number[]) {
  await page.getByRole("button", { name: "Select", exact: true }).click();
  for (const id of ids) {
    await page
      .getByRole("checkbox", { name: `Select spool #${id}`, exact: true })
      .check();
  }
  await bar(page).getByRole("button", { name: "Weigh in" }).click();
  await expect(dialog(page)).toBeVisible();
}

async function pickMeasuredWeightMode(page: Page) {
  await dialog(page)
    .getByRole("button", { name: "Measured Weight", exact: true })
    .click();
}

test("measured-weight readings for two spools land the hand-computed remaining weight", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedTwo(request);
  await openAt(page, location);
  await selectAndOpenWeighIn(page, ids);

  await expect(dialog(page)).toContainText("1 of 2");
  await expect(dialog(page)).toContainText(`#${ids[0]}`);
  await pickMeasuredWeightMode(page);

  const input = dialog(page).getByRole("textbox");
  const firstGross = 690;
  await input.fill(String(firstGross));
  await page.getByRole("button", { name: "Save & Next" }).click();

  await expect(dialog(page)).toContainText("2 of 2");
  await expect(dialog(page)).toContainText(`#${ids[1]}`);
  // The mode is remembered across spools within the same weigh-in.
  await expect(
    dialog(page).getByRole("button", { name: "Measured Weight", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");

  const secondGross = 890;
  await dialog(page).getByRole("textbox").fill(String(secondGross));
  await page.getByRole("button", { name: "Save & Next" }).click();

  await expect(dialog(page).getByRole("status")).toHaveText(
    "2 updated, 0 skipped, 0 failed",
  );
  // The dialog also has its own "x" close button with the same accessible name; the footer's
  // submit button is the one after it in the DOM.
  await dialog(page)
    .getByRole("button", { name: "Close", exact: true })
    .last()
    .click();
  await expect(dialog(page)).toHaveCount(0);

  await expect
    .poll(async () => remainingWeightOf(request, ids[0]))
    .toBeCloseTo(remainingFor(firstGross), 3);
  await expect
    .poll(async () => remainingWeightOf(request, ids[1]))
    .toBeCloseTo(remainingFor(secondGross), 3);
});

test("a negative measured-weight reading is refused client-side and sends no request", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedTwo(request);
  const before = await remainingWeightOf(request, ids[0]);
  await openAt(page, location);
  await selectAndOpenWeighIn(page, [ids[0]]);
  await pickMeasuredWeightMode(page);

  const measureRequests: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/measure")) measureRequests.push(r.url());
  });

  await dialog(page).getByRole("textbox").fill("-5");
  await page.getByRole("button", { name: "Save & Next" }).click();

  await expect(dialog(page).getByRole("alert")).toHaveText(
    "Enter a valid weight.",
  );

  await expect(
    page.waitForRequest((r) => r.url().includes("/measure"), { timeout: 1000 }),
  ).rejects.toThrow();
  expect(measureRequests).toHaveLength(0);

  // Still on the same spool, which kept its weight.
  await expect(dialog(page)).toContainText("1 of 1");
  expect(await remainingWeightOf(request, ids[0])).toBe(before);
});

test("skip leaves the spool unchanged and moves to weighing the next one", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedTwo(request);
  await openAt(page, location);
  await selectAndOpenWeighIn(page, ids);

  const before = await remainingWeightOf(request, ids[0]);
  await page.getByRole("button", { name: "Skip" }).click();

  await expect(dialog(page)).toContainText("2 of 2");
  await expect(dialog(page)).toContainText(`#${ids[1]}`);

  await pickMeasuredWeightMode(page);
  await dialog(page).getByRole("textbox").fill("700");
  await page.getByRole("button", { name: "Save & Next" }).click();

  await expect(dialog(page).getByRole("status")).toHaveText(
    "1 updated, 1 skipped, 0 failed",
  );

  const after = await remainingWeightOf(request, ids[0]);
  expect(after).toBe(before);
  await expect
    .poll(async () => remainingWeightOf(request, ids[1]))
    .toBeCloseTo(remainingFor(700), 3);
});

test("the chosen weigh-in mode is remembered under its localStorage key", async ({
  page,
  request,
}) => {
  const { location, ids } = await seedTwo(request);
  await openAt(page, location);
  await selectAndOpenWeighIn(page, [ids[0]]);

  await pickMeasuredWeightMode(page);

  await expect
    .poll(() =>
      page.evaluate(() => localStorage.getItem("spoolman-v2-adjust-mode")),
    )
    .toBe("measured_weight");
});
