import { test, expect } from "./camera";
import { seedFilament, seedLocation, seedSpool, spoolById, unique } from "./helpers";

/**
 * The scan cases this fork adds to upstream's QR scanner: the clear sentinel (#132), scan-to-move
 * (#84) and the retail-barcode lookup (#97b).
 *
 * Driven through a real camera rather than by calling the handler, because what these tests are
 * for is the wiring. The decision logic underneath already has 183 unit tests and needs no
 * browser; what only a browser can show is that the fork's handler is actually reached from
 * inside the vendored modal, that declining a scan really does fall through to upstream's own
 * navigation, and that the state machine survives a camera feeding it the same label five times
 * a second. See ./qrVideo for how the frames are made.
 *
 * A note on the barcode tests: the fake camera decodes QR, not EAN. That is not a compromise --
 * `looksLikeRetailBarcode` classifies by digits and length and never sees the symbology, so a QR
 * carrying thirteen digits reaches the retail path by exactly the route a real EAN-13 does.
 */

const scanner = (page: import("@playwright/test").Page) =>
  page.getByRole("dialog", { name: "QR Code Scanner" });

async function openScanner(page: import("@playwright/test").Page) {
  await page.goto("/", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "QR Code Scanner" }).click();
  await expect(scanner(page)).toBeVisible();
}

test("a spool code still navigates, so the fork handler has not swallowed upstream's case", async ({
  cameraPage,
  request,
}) => {
  // The delegation returns false for an 'open'-mode entity scan precisely so the vendored
  // navigation keeps running. Nothing in the fork's own tests would notice if that stopped.
  const { spoolId } = await seedSpool(request, "ScanOpen", "Shelf Open");
  const page = await cameraPage([`WEB+SPOOLMAN:S-${spoolId}`]);

  await openScanner(page);

  await page.waitForURL(new RegExp(`sel=spool:${spoolId}\\b`), { timeout: 20_000 });
});

test("the reserved clear code is acknowledged rather than silently ignored", async ({ cameraPage }) => {
  // Spoolman holds no active spool of its own, so there is nothing to clear here. Saying so is
  // the whole feature: a code other integrations agree on must not look like a dud label.
  const page = await cameraPage(["WEB+SPOOLMAN:CLEAR"]);

  await openScanner(page);

  await expect(page.getByText(/Clear-spool code recognized/i)).toBeVisible({ timeout: 20_000 });
  await expect(scanner(page)).toBeHidden();
});

test("move mode relocates a spool from a spool label and then a location label", async ({
  cameraPage,
  request,
}) => {
  const start = unique("Bench");
  const { spoolId } = await seedSpool(request, "ScanMove", start);
  const destination = await seedLocation(request, "ScanShelf");
  const page = await cameraPage([`WEB+SPOOLMAN:S-${spoolId}`, `WEB+SPOOLMAN:L-${destination.id}`]);

  await openScanner(page);
  await page.getByRole("button", { name: "Move spool" }).click();
  await expect(page.getByText("Scan a spool to move")).toBeVisible();

  // First label: the spool is held, and the prompt names it so the user can see WHICH spool the
  // scanner grabbed before they go looking for a shelf.
  await expect(page.getByText(`Spool #${spoolId} selected`)).toBeVisible({ timeout: 20_000 });

  // Second label: the confirmation names the location, not its id -- the point of the fetch it
  // costs is that the user can tell they scanned the right shelf.
  const confirm = page.getByRole("dialog", { name: "Move spool?" });
  await expect(confirm).toBeVisible({ timeout: 20_000 });
  await expect(confirm).toContainText(destination.name);
  await expect(confirm).toContainText(`#${spoolId}`);

  await confirm.getByRole("button", { name: "Move spool" }).click();

  await expect(page.getByText(`Moved spool #${spoolId}`)).toBeVisible();
  await expect(scanner(page)).toBeHidden();
  // The toast is a claim about the database, so check the database.
  await expect
    .poll(async () => (await spoolById(request, spoolId)).location)
    .toBe(destination.name);
});

test("move mode holds its spool while the same label stays in view", async ({
  cameraPage,
  request,
}) => {
  // The camera re-decodes a held label several times a second. Treating each one as a fresh
  // event would either nag or drop the capture; the state machine says it is nothing to report,
  // and this is the only place that claim meets a real camera.
  const { spoolId } = await seedSpool(request, "ScanHold", unique("Bench"));
  const page = await cameraPage([`WEB+SPOOLMAN:S-${spoolId}`]);

  await openScanner(page);
  await page.getByRole("button", { name: "Move spool" }).click();
  await expect(page.getByText(`Spool #${spoolId} selected`)).toBeVisible({ timeout: 20_000 });

  await page.waitForTimeout(3000);
  await expect(page.getByText(`Spool #${spoolId} selected`)).toBeVisible();
  await expect(scanner(page)).toBeVisible();
});

test("a retail barcode a filament claims opens Add spools on that filament", async ({
  cameraPage,
  request,
}) => {
  const barcode = `40${Date.now().toString().slice(-11)}`;
  const filament = await seedFilament(request, "ScanBarcode", barcode);
  const page = await cameraPage([barcode]);

  await openScanner(page);

  // The Add-spools modal carries no accessible name of its own, so it is picked out by the
  // title it renders rather than by an aria-label it does not have.
  const add = page.getByRole("dialog").filter({ hasText: "Add spools" });
  await expect(add).toBeVisible({ timeout: 20_000 });
  // Opened ON the matched filament, not merely opened: a search step listing everything is
  // what the user would have got by pressing Add themselves, and the scan would have bought
  // them nothing.
  await expect(add.getByRole("textbox", { name: /Search your catalog/i })).toBeHidden();
  await expect(add).toContainText(filament.name);
});

test("a retail barcode nothing claims offers a filament that will remember it", async ({
  cameraPage,
}) => {
  // A dead end here is what the feature exists to remove: the user is holding the spool, the
  // barcode is on it, and retyping thirteen digits is the friction.
  const barcode = `41${Date.now().toString().slice(-11)}`;
  const page = await cameraPage([barcode]);

  await openScanner(page);

  const prompt = page.getByRole("dialog", { name: "Unknown barcode" });
  await expect(prompt).toBeVisible({ timeout: 20_000 });
  await expect(prompt).toContainText(barcode);

  await prompt.getByRole("button", { name: "Create filament" }).click();

  const add = page.getByRole("dialog").filter({ hasText: "Add spools" });
  await expect(add).toBeVisible();
  // The barcode is carried into the new filament's article number, which is what makes the NEXT
  // scan of this spool resolve instead of asking again -- and it is VISIBLE, not just set: the
  // field lives in the advanced block, which this flow has to open or the value sits behind a
  // collapsed heading where the user can neither check nor correct it.
  await expect(add.getByRole("textbox", { name: /Article Number/i })).toHaveValue(barcode);
});

test("a retail barcode is ignored mid-move, so a half-finished move is not lost", async ({
  cameraPage,
  request,
}) => {
  const { spoolId } = await seedSpool(request, "ScanMixed", unique("Bench"));
  const page = await cameraPage([`WEB+SPOOLMAN:S-${spoolId}`, `42${Date.now().toString().slice(-11)}`]);

  await openScanner(page);
  await page.getByRole("button", { name: "Move spool" }).click();
  await expect(page.getByText(`Spool #${spoolId} selected`)).toBeVisible({ timeout: 20_000 });

  // The barcode frames come round repeatedly; none of them may raise a filament dialog.
  await page.waitForTimeout(4000);
  await expect(page.getByRole("dialog", { name: "Unknown barcode" })).toBeHidden();
  await expect(page.getByText(`Spool #${spoolId} selected`)).toBeVisible();
});
