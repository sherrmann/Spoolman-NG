import { expect, test, type APIRequestContext } from "@playwright/test";
import { seedFilament, unique } from "./helpers";

/**
 * The unit-scaling control (client_v2/src/lib/ng/components/UnitScalingRow.svelte) and what it
 * does to every weight on screen (#413).
 *
 * The setting starts unset on a fresh database, and in this client that means "scale" -- the
 * behaviour the vendored upstream suite pins with its "1 kg" preset button. So the first test
 * states the default, and the rest flip the switch and read a real spool's weight back from
 * the inspector, which is the oracle: not the switch's own state, but what a user sees.
 */

async function setSetting(request: APIRequestContext, key: string, value: unknown) {
  const res = await request.post(`/api/v1/setting/${key}`, {
    headers: { "Content-Type": "application/json" },
    // Double-encoded: the body is the JSON encoding of the stored JSON string. The string
    // "null" resets the setting to unset, which is the state the other specs expect.
    data: JSON.stringify(JSON.stringify(value)),
  });
  // Resetting a setting that was never set answers 404; that is the state being asked for.
  if (res.status() === 404 && value === null) return;
  if (!res.ok()) throw new Error(`setting ${key} -> ${res.status()} ${await res.text()}`);
}

/** A 1.5 kg spool of a 1.5 kg filament, untouched, so its remaining weight is 1500 g. */
async function seedHeavySpool(request: APIRequestContext) {
  const filament = await seedFilament(request, "Scaling");
  const patched = await request.patch(`/api/v1/filament/${filament.id}`, {
    data: { weight: 1500 },
  });
  if (!patched.ok()) throw new Error(`filament weight -> ${patched.status()}`);
  const res = await request.post("/api/v1/spool", {
    data: { filament_id: filament.id, location: unique("Bench") },
  });
  if (!res.ok()) throw new Error(`spool -> ${res.status()}`);
  return ((await res.json()) as { id: number }).id;
}

const toggle = (page: import("@playwright/test").Page) =>
  page.getByRole("switch", { name: "Scale large units" });

test.afterEach(async ({ request }) => {
  await setSetting(request, "unit_scaling", null);
});

test("an unset setting keeps upstream's behaviour: kilograms from 1000 g", async ({
  page,
  request,
}) => {
  await setSetting(request, "unit_scaling", null);
  const spoolId = await seedHeavySpool(request);

  await page.goto(`/?sel=spool:${spoolId}`, { waitUntil: "networkidle" });
  await expect(page.getByText("1.5 kg", { exact: true }).first()).toBeVisible();

  // And the switch reports the effective state, not the (unset) stored one.
  await page.goto("/settings", { waitUntil: "networkidle" });
  await expect(toggle(page)).toHaveAttribute("aria-checked", "true");
});

test("switching it off shows raw grams, and switching it on brings kilograms back", async ({
  page,
  request,
}) => {
  const spoolId = await seedHeavySpool(request);

  await page.goto("/settings", { waitUntil: "networkidle" });
  await toggle(page).click();
  await expect(toggle(page)).toHaveAttribute("aria-checked", "false");
  // The write is the contract: the React client reads the same key.
  const stored = await (await request.get("/api/v1/setting/unit_scaling")).json();
  expect(stored).toMatchObject({ value: "false", is_set: true });

  await page.goto(`/?sel=spool:${spoolId}`, { waitUntil: "networkidle" });
  await expect(page.getByText("1500 g", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("1.5 kg", { exact: true })).toHaveCount(0);

  await page.goto("/settings", { waitUntil: "networkidle" });
  await toggle(page).click();
  await expect(toggle(page)).toHaveAttribute("aria-checked", "true");

  await page.goto(`/?sel=spool:${spoolId}`, { waitUntil: "networkidle" });
  await expect(page.getByText("1.5 kg", { exact: true }).first()).toBeVisible();
});

test("the new controls do not collide with the labels upstream's own specs query", async ({
  page,
}) => {
  // Upstream's settings spec finds these page-wide, and a second match is a strict-mode
  // failure in their suite. Everything this fork adds to the page must leave them unique.
  await page.goto("/settings", { waitUntil: "networkidle" });
  await expect(toggle(page)).toBeVisible();
  await expect(page.getByLabel("Base URL")).toHaveCount(1);
  await expect(page.getByLabel("Currency")).toHaveCount(1);
  await expect(page.getByLabel("Round prices")).toHaveCount(1);
  await expect(page.getByRole("textbox", { name: "Low-stock threshold" })).toHaveCount(1);
  await expect(page.getByRole("group", { name: "Theme" })).toHaveCount(1);
});
