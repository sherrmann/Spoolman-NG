import { Page, expect, test } from "@playwright/test";

/**
 * The per-browser switch between this fork's two web clients.
 *
 * Everything else about this feature is unit-tested on both sides and at the HTTP boundary
 * (tests/test_client_serving.py, tests/integration/test_client_selector.py). What none of those
 * can see is the round trip: that clicking the control in one client actually lands you in the
 * other one, and that you can get back. A one-way switch would be the worst possible failure —
 * a user stranded in a client they did not choose, with no way home.
 *
 * This is also the only suite whose deployment has both bundles built (see the "Build the legacy
 * client too" step in the tests-frontend-ng CI job); everywhere else the control hides itself
 * because there is nothing to switch to.
 */

/** The React client mounts into #root; the Svelte client has no equivalent. */
const REACT_SHELL = "#root";

/** How many service workers this origin currently has registered. */
function registrationCount(page: Page): Promise<number> {
  return page.evaluate(async () => {
    if (!("serviceWorker" in navigator)) return 0;
    return (await navigator.serviceWorker.getRegistrations()).length;
  });
}

test("a browser can move to the other client and back again", async ({ page, context }) => {
  await page.goto("/settings");

  // The Svelte client is what this deployment serves by default (SPOOLMAN_LEGACY_CLIENT=FALSE),
  // and its switcher lives with the other appearance settings.
  const svelteSwitch = page.getByRole("group", { name: "Interface" });
  await expect(svelteSwitch).toBeVisible();
  await expect(svelteSwitch.getByRole("button", { name: "New" })).toHaveAttribute("aria-pressed", "true");

  await test.step("switching to the classic client lands in it", async () => {
    await svelteSwitch.getByRole("button", { name: "Classic" }).click();
    await expect(page.locator(REACT_SHELL)).toBeVisible();
    // The URL is untouched by the switch: both clients answer the same paths, which is what
    // keeps bookmarks and printed QR labels working across it.
    await expect(page).toHaveURL(/\/settings$/);
  });

  await test.step("the choice is stored in this browser, not on the server", async () => {
    const cookie = (await context.cookies()).find((c) => c.name === "spoolman_ui");
    expect(cookie?.value).toBe("react");
  });

  await test.step("the classic client registers the service worker the way back has to clear", async () => {
    // Proves the trap is real before asserting it is sprung: without this, the final assertion
    // would pass just as happily against a browser that never registered anything.
    await expect.poll(() => registrationCount(page)).toBeGreaterThan(0);
  });

  await test.step("switching back returns to the new client", async () => {
    // The React client keeps its appearance controls in the header rather than on a settings
    // page, so the way back is there — on every route, not just this one.
    const reactSwitch = page.getByRole("radiogroup", { name: "Interface" });
    await expect(reactSwitch.getByRole("radio", { name: "Classic" })).toBeChecked();
    await reactSwitch.getByText("New", { exact: true }).click();

    await expect(page.getByRole("group", { name: "Interface" })).toBeVisible();
    await expect(page.locator(REACT_SHELL)).toHaveCount(0);
  });

  await test.step("the classic client's service worker does not outlive the switch", async () => {
    // Its precache belongs to a client that is no longer being served. client_v2 ships a
    // self-destructing worker for exactly this, but that only runs when the browser next checks
    // for a worker update — so the switch tears the registration down itself, and this is the
    // assertion that says it really did.
    await expect.poll(() => registrationCount(page)).toBe(0);
  });
});
