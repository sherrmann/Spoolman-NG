import { expect, test, type Page } from "@playwright/test";
import { post, seedLocation, seedLowFilament, seedOrder, unique } from "../helpers";
import { deviceProblems, expectDeviceReady, expectDialogFits } from "./checks";

/**
 * Every page of the Svelte client, upstream's and this fork's alike, on each device class the
 * playwright config lists as a `device-*` project: small and large phones, a tablet held both
 * ways, a laptop and a desktop monitor. The client switches layout at 860px, so the tablet in
 * portrait gets the phone chrome and in landscape the desktop one -- both need to hold up.
 *
 * Each page gets the same checks (see ./checks.ts and ../mobile/layout.ts): nothing scrolls
 * sideways or is pushed out of reach, nothing covers a control, tap targets are large enough on
 * touch devices, and text is styled in upstream's design language. The phone-only behaviours
 * (bottom bar, inspector sheet, search overlay) stay in ../mobile/mobile.spec.ts.
 */

const ROUTES = [
  "/",
  "/home",
  "/lowstock",
  "/orders",
  "/dashboard",
  "/locations",
  "/calibration",
  "/labels",
  "/settings",
  "/help",
];

let locationId: number;
let spoolId: number;

test.beforeAll(async ({ playwright, baseURL }) => {
  const api = await playwright.request.newContext({ baseURL });
  // Long names on purpose: they are what pushes a narrow layout past its edge.
  const vendor = await post(api, "/vendor", {
    name: unique("Device Vendor Long Registered Company Name GmbH"),
    empty_spool_weight: 190,
  });
  const filament = await post(api, "/filament", {
    name: unique("Device Galaxy Black Silk Matte Filament Long Name"),
    vendor_id: vendor.id,
    material: "PLA",
    color_hex: "1A1A2E",
    price: 24.99,
    density: 1.24,
    diameter: 1.75,
    weight: 1000,
    spool_weight: 190,
  });
  const location = await seedLocation(api, "Device Shelf");
  spoolId = (await post(api, "/spool", { filament_id: filament.id, used_weight: 350, location: location.name })).id;
  // Low Stock and Home list filaments, not spools, by what their spools have left: this one's single
  // spool has 50 g, and nothing orders it, so its row carries the selection checkbox too.
  await seedLowFilament(api, "Device");
  await seedOrder(api, "Device");
  await api.dispose();
  locationId = location.id;
});

async function open(page: Page, path: string) {
  await page.goto(path, { waitUntil: "networkidle" });
  await expect(page.locator("header.topbar")).toBeVisible();
}

for (const path of [...ROUTES, "location detail"]) {
  test(`${path} holds up on this device`, async ({ page, hasTouch }) => {
    // The collector scrolls controls into view one by one; a board with a large shared database
    // behind it takes a while.
    test.setTimeout(60_000);
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const url = path === "location detail" ? `/location/show/${locationId}` : path;
    await open(page, url);
    await expectDeviceReady(page, url, { touch: hasTouch });
    expect(errors, "uncaught exceptions").toEqual([]);
  });
}

test.describe("dialogs", () => {
  async function checkDialog(page: Page, hasTouch: boolean, what: string) {
    const dialog = page.getByRole("dialog").last();
    await expectDialogFits(page, dialog, what);
    await expectDeviceReady(page, what, { touch: hasTouch, scope: '[role="dialog"]' });
  }

  test("adding spools", async ({ page, hasTouch }) => {
    await open(page, "/");
    await page.getByRole("button", { name: "Add spools", exact: true }).click();
    await checkDialog(page, hasTouch, "the add-spools dialog");
  });

  test("a new order", async ({ page, hasTouch }) => {
    await open(page, "/orders");
    await page.getByRole("button", { name: "New order" }).click();
    await checkDialog(page, hasTouch, "the new-order dialog");
  });

  test("a new location", async ({ page, hasTouch }) => {
    await open(page, "/locations");
    await page.getByRole("button", { name: "New Location" }).click();
    await checkDialog(page, hasTouch, "the new-location dialog");
  });

  test("an order's details and its arrival", async ({ page, hasTouch }) => {
    await open(page, "/orders");
    const row = page.getByRole("listitem").filter({ hasText: "Device-SO" }).first();
    await row.locator(".order-link").click();
    await checkDialog(page, hasTouch, "the order-details dialog");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await row.getByRole("button", { name: /Arrived/ }).click();
    await checkDialog(page, hasTouch, "the arrival dialog");
  });

  test("the spool inspector", async ({ page, hasTouch }) => {
    // The seeded spool, not whichever sorts first: other specs leave spools behind in the shared
    // database, and the result must not depend on them.
    await open(page, `/?sel=spool:${spoolId}`);
    // A side pane on wide screens, a bottom sheet under 860px; either way it is the .pane.
    const pane = page.locator(".pane");
    await expect(pane.getByText(/remaining/i).first()).toBeVisible();
    await expectDeviceReady(page, "the spool inspector", { touch: hasTouch, scope: ".pane" });
  });
});

test("the checks report what they claim to", async ({ page }, testInfo) => {
  // Guards the checks themselves: a check that silently stopped matching would pass every page
  // above. Run once, on the touch phone, against deliberately broken markup.
  test.skip(testInfo.project.name !== "device-phone", "runs once, on a touch device");
  await open(page, "/help");
  await page.evaluate(() => {
    const box = document.createElement("div");
    box.id = "broken";
    box.innerHTML = `
      <button id="tiny" style="width:12px;height:12px;padding:0">a</button>
      <button id="tiny2" style="width:12px;height:12px;padding:0">b</button>
      <button id="hidden-under">covered</button>
      <span style="font-family: Georgia; font-weight: 900">off-design</span>
      <span class="off-colour">off-colour</span>`;
    document.querySelector("main")!.prepend(box);
    const style = document.createElement("style");
    style.textContent = ".off-colour { color: rgb(1, 2, 3); }";
    document.head.appendChild(style);
    const under = document.getElementById("hidden-under")!.getBoundingClientRect();
    const cover = document.createElement("div");
    Object.assign(cover.style, {
      position: "fixed",
      left: `${under.left - 4}px`,
      top: `${under.top - 4}px`,
      width: `${under.width + 8}px`,
      height: `${under.height + 8}px`,
      zIndex: "999",
      background: "red",
    });
    cover.className = "cover";
    document.body.appendChild(cover);
  });
  const lines = (await deviceProblems(page, { touch: true, scope: "#broken" })).map((p) => `${p.kind}: ${p.detail}`);
  const expected = [
    /^tap-target-too-small: <button> "a"/,
    /^control-covered: <button> "covered" is covered by <div\.cover>/,
    /^off-design-style: <span> "off-design" uses font Georgia/,
    /^off-design-style: <span> "off-design" uses weight 900/,
    /^off-design-style: <span\.off-colour> "off-colour" uses colour rgb\(1, 2, 3\)/,
  ];
  for (const re of expected)
    expect(
      lines.some((l) => re.test(l)),
      `${re} in:\n${lines.join("\n")}`,
    ).toBe(true);
});
