import { expect, test, type Locator, type Page } from "@playwright/test";
import { calibrationSession, calibrationSessions, seedFilament } from "./helpers";

/**
 * The fork's Calibration page and wizard (client_v2/src/routes/calibration/).
 *
 * Every bug this page shipped with was an INTERACTION bug that unit tests could not have
 * caught -- the arithmetic was already covered by 135 of them and all of it was correct. What
 * was broken was what happened when you pressed the buttons: Save persisted the step and then
 * silently stayed on it, and Skip wrote a permanent "skipped" marker where it should have
 * written nothing. So this suite asserts the WIRING, and asserts it against the server rather
 * than against the screen: whether a step exists after a click is the only question that
 * matters, and only the API can answer it.
 *
 * Typing convention, learned the hard way: this client's NumberInput commits on blur or step,
 * never per keystroke (see $components/NumberInput.svelte). `fill()` sets the DOM value
 * without ever committing it, so a test using it watches a field that looks filled while the
 * component behind it still holds null -- which made working code look broken twice while
 * this page was being written. Always pressSequentially + blur; `type()` below does both.
 */

const dialog = (page: Page) => page.getByRole("dialog");

/** Type into the nth number field of the open dialog and commit it. */
async function type(page: Page, nth: number, value: string | number) {
  const input = dialog(page).locator('input[type="text"]').nth(nth);
  await input.click();
  await input.pressSequentially(String(value), { delay: 20 });
  await input.blur();
}

/** The wizard's "Step N of 9" counter, as a number. */
async function stepNumber(page: Page): Promise<number> {
  const text = await dialog(page).innerText();
  const match = text.match(/(\d+)\s*of\s*9/);
  expect(match, `no step counter in the dialog:\n${text.slice(0, 200)}`).not.toBeNull();
  return Number(match![1]);
}

async function openWizard(page: Page, filamentId: number) {
  await page.goto(`/calibration?filament=${filamentId}`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /start wizard/i }).click();
  await expect(dialog(page)).toBeVisible();
}

const footer = (page: Page, name: RegExp): Locator =>
  dialog(page).getByRole("button", { name });

test("the wizard opens on the first step with all nine listed", async ({ page, request }) => {
  const filament = await seedFilament(request, "CalOpen");
  await openWizard(page, filament.id);

  expect(await stepNumber(page)).toBe(1);
  // The sidebar is rendered from WIZARD_STEP_ORDER, which both clients and the API agree on.
  await expect(dialog(page).getByRole("button", { name: /temperature/i })).toBeVisible();
  await expect(dialog(page).getByRole("button", { name: /vfa/i })).toBeVisible();
});

test("saving a step records it and moves on", async ({ page, request }) => {
  // The regression that matters most here. navigateTo() used to refuse to move while a save
  // was in flight, which also blocked the advance that runs straight after one -- so every
  // Save & Continue wrote the step and left you looking at it. Asserting the step count alone
  // would have passed while that was broken; the step NUMBER is the half that catches it.
  const filament = await seedFilament(request, "CalSave");
  await openWizard(page, filament.id);

  await type(page, 0, 190);
  await type(page, 1, 230);
  await type(page, 2, 5);
  await type(page, 3, 215);
  await footer(page, /save & continue/i).click();

  await expect.poll(() => stepNumber(page)).toBe(2);

  const [session] = await calibrationSessions(request, filament.id);
  const saved = await calibrationSession(request, session.id);
  expect(saved.steps.map((s) => s.step_type)).toEqual(["temperature"]);
  expect(saved.steps[0].selected_values).toEqual({ temperature: 215 });
});

test("skipping a step records nothing at all", async ({ page, request }) => {
  // Skip means "not now", not "never" -- the wizard's own subtitle promises you can resume
  // later, and the finish prompt says "without saving this step". A version of this page
  // wrote the _skipped sentinel here, which would leave anyone who meant "later" with a step
  // marked permanently skipped and no way back but deleting it.
  const filament = await seedFilament(request, "CalSkip");
  await openWizard(page, filament.id);

  await footer(page, /^skip$/i).click();
  await expect.poll(() => stepNumber(page)).toBe(2);

  const [session] = await calibrationSessions(request, filament.id);
  expect((await calibrationSession(request, session.id)).steps).toHaveLength(0);
});

test("an auto-computed result fills itself in from the inputs", async ({ page, request }) => {
  const filament = await seedFilament(request, "CalAuto");
  await openWizard(page, filament.id);
  await dialog(page).getByRole("button", { name: /volumetric speed/i }).click();

  // start + height x step = 5 + 12 x 0.5 = 11
  await type(page, 0, 5);
  await type(page, 1, 0.5);
  await type(page, 2, 12);

  await expect(dialog(page).locator('input[type="text"]').nth(3)).toHaveValue("11");
});

test("the flow calculator applies its result to the result field", async ({ page, request }) => {
  const filament = await seedFilament(request, "CalFlow");
  await openWizard(page, filament.id);
  await dialog(page).getByRole("button", { name: /flow rate/i }).click();

  // YOLO: the modifier is an ABSOLUTE adjustment, so 1.0 + 0.02 = 1.02. (The legacy method
  // reads the same number as a percentage -- see calibrationCalc.ts.)
  await type(page, 1, 0.02);
  const apply = dialog(page).getByRole("button", { name: /apply/i });
  await expect(apply).toBeEnabled();
  await apply.click();

  await expect(dialog(page).locator('input[type="text"]').nth(2)).toHaveValue("1.02");
});

test("cancelling leaves the session resumable at the first unrecorded step", async ({
  page,
  request,
}) => {
  const filament = await seedFilament(request, "CalResume");
  await openWizard(page, filament.id);

  await type(page, 0, 190);
  await type(page, 1, 230);
  await type(page, 2, 5);
  await type(page, 3, 215);
  await footer(page, /save & continue/i).click();
  await expect.poll(() => stepNumber(page)).toBe(2);
  await footer(page, /cancel/i).click();
  await expect(dialog(page)).toBeHidden();

  const [session] = await calibrationSessions(request, filament.id);
  expect(session.status, "cancelling must not complete the session").toBe("in_progress");

  await page.getByRole("button", { name: /resume wizard/i }).click();
  await expect(dialog(page)).toBeVisible();
  expect(await stepNumber(page)).toBe(2);
});

test("a recorded step shows up in the calibrated settings summary", async ({ page, request }) => {
  const filament = await seedFilament(request, "CalSummary");
  await openWizard(page, filament.id);
  await type(page, 0, 190);
  await type(page, 1, 230);
  await type(page, 2, 5);
  await type(page, 3, 215);
  await footer(page, /save & continue/i).click();
  await expect.poll(() => stepNumber(page)).toBe(2);
  await footer(page, /cancel/i).click();

  // The summary is built from the steps' selected_values, not from their raw outputs.
  await expect(page.getByText(/215/).first()).toBeVisible();
});

test("the filament inspector links into that filament's calibration", async ({ page, request }) => {
  // The one deep link into this page from upstream's own UI, and the only reason a user ever
  // arrives here with a filament already chosen.
  const filament = await seedFilament(request, "CalLink");
  await page.goto(`/?sel=filament:${filament.id}`, { waitUntil: "networkidle" });

  // Scoped away from the nav bar on purpose: the top nav also has a "Calibration" link (twice
  // over -- desktop and mobile), and both point at the bare /calibration with no filament. A
  // `.first()` here silently tested the nav tab instead, which passes whatever the inspector
  // does. Match on the href that actually carries the filament.
  const link = page.locator(`a[href*="/calibration?filament=${filament.id}"]`);
  await expect(link).toHaveCount(1);
  await link.click();

  await expect(page).toHaveURL(new RegExp(`/calibration\\?filament=${filament.id}`));
  await expect(page.getByRole("button", { name: /start wizard/i })).toBeVisible();
});

test("the page scrolls inside the app shell rather than overflowing it", async ({
  page,
  request,
}) => {
  const filament = await seedFilament(request, "CalScroll");
  await page.setViewportSize({ width: 700, height: 800 });
  await page.goto(`/calibration?filament=${filament.id}`, { waitUntil: "networkidle" });
  const { docScroll, viewport } = await page.evaluate(() => ({
    docScroll: document.documentElement.scrollHeight,
    viewport: window.innerHeight,
  }));
  expect(docScroll, `the document grew to ${docScroll}px`).toBeLessThanOrEqual(viewport + 1);
});
