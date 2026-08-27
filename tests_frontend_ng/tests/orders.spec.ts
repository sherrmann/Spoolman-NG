import { expect, test, type Page } from "@playwright/test";
import { orderById, seedOrder } from "./helpers";

/**
 * The fork's Orders page (client_v2/src/routes/orders/).
 *
 * PATCH /order/{id} replaces the ENTIRE line set whenever `lines` is present -- the API has no
 * per-line endpoint. So the edit path has to resend every line, and the test that matters most
 * here is not "does an edit save" but "does editing one line silently drop the others".
 */

const row = (page: Page, text: string) =>
  page.getByRole("listitem").filter({ hasText: text }).first();

async function openOrders(page: Page) {
  await page.goto("/orders", { waitUntil: "networkidle" });
  await expect(page.getByRole("listitem").first()).toBeVisible();
}

test("lists orders with their state and shop", async ({ page, request }) => {
  const seeded = await seedOrder(request, "List");
  await openOrders(page);

  await expect(page).toHaveTitle(/Orders/);
  const r = row(page, seeded.orderNumber);
  await expect(r).toContainText(seeded.shopName);
  // Summary counts distinct filaments, not lines -- a split line must not double count.
  await expect(r).toContainText(/0 of 7 arrived/);
  await expect(r).toContainText(/2 filaments/);
});

test("?highlight= opens that order's details", async ({ page, request }) => {
  // These links are written by Low Stock and Home. The React client never read the parameter,
  // so they were dead ends there; this asserts they are not dead ends here.
  const seeded = await seedOrder(request, "Hl");
  await page.goto(`/orders?highlight=${seeded.orderId}`, {
    waitUntil: "networkidle",
  });

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(seeded.orderNumber);
});

test("editing one line keeps the others, rather than replacing the line set", async ({
  page,
  request,
}) => {
  const seeded = await seedOrder(request, "Edit");

  await page.goto(`/orders?highlight=${seeded.orderId}`, {
    waitUntil: "networkidle",
  });
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  // Deliberately no blur between typing and saving: that is what a user does, and it is exactly
  // the sequence that used to lose the edit -- NumberInput commits on blur, so the save handler
  // read the pre-typing value and reported success. Adding a Tab here would hide that bug again.
  await dialog
    .getByLabel(new RegExp(`Quantity — .*${seeded.first.name}`))
    .fill("9");
  // Wait for the write itself, rather than polling the API and hoping it has landed. An earlier
  // version polled `lines.length === 2`, which is true both before and after the edit, so it
  // returned on its first sample and read the order back ~68ms before the PATCH completed --
  // passing or failing on timing alone.
  const patched = page.waitForResponse(
    (r) =>
      r.request().method() === "PATCH" &&
      r.url().includes(`/order/${seeded.orderId}`),
  );
  await dialog.getByRole("button", { name: /^Save$/ }).click();
  expect((await patched).status(), "the save should be accepted").toBe(200);

  const after = await orderById(request, seeded.orderId);
  expect(after.lines, "the order should still have both lines").toHaveLength(2);
  const edited = after.lines.find((l) => l.filament_id === seeded.first.id);
  const untouched = after.lines.find((l) => l.filament_id === seeded.second.id);
  expect(
    edited?.quantity,
    "the edited line should carry the new quantity",
  ).toBe(9);
  // The whole point: the line nobody touched must come back unchanged, not vanish.
  expect(
    untouched?.quantity,
    "the untouched line should survive a full-set replace",
  ).toBe(5);
});

test("marking an order arrived closes it out", async ({ page, request }) => {
  const seeded = await seedOrder(request, "Arr");
  expect((await orderById(request, seeded.orderId)).state).toBe("open");

  await openOrders(page);
  await row(page, seeded.orderNumber)
    .getByRole("button", { name: /arrived/i })
    .click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /mark arrived/i }).click();

  await expect
    .poll(() => orderById(request, seeded.orderId).then((o) => o.state), {
      timeout: 10_000,
    })
    .toBe("arrived");
});

test("deleting an order asks first, and removes it once confirmed", async ({
  page,
  request,
}) => {
  const seeded = await seedOrder(request, "Del");
  await page.goto(`/orders?highlight=${seeded.orderId}`, {
    waitUntil: "networkidle",
  });

  const dialog = page.getByRole("dialog").first();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /delete/i }).click();

  // A confirm step stands between the button and the deletion; the order still exists here.
  expect((await orderById(request, seeded.orderId)).lines).toHaveLength(2);

  await page
    .getByRole("dialog")
    .last()
    .getByRole("button", { name: /delete|confirm/i })
    .click();

  await expect
    .poll(
      async () =>
        (await request.get(`/api/v1/order/${seeded.orderId}`)).status(),
      { timeout: 10_000 },
    )
    .toBe(404);
});

test("the page scrolls inside the app shell rather than overflowing it", async ({
  page,
}) => {
  await page.setViewportSize({ width: 700, height: 800 });
  await openOrders(page);
  const { docScroll, viewport } = await page.evaluate(() => ({
    docScroll: document.documentElement.scrollHeight,
    viewport: window.innerHeight,
  }));
  expect(docScroll, `the document grew to ${docScroll}px`).toBeLessThanOrEqual(
    viewport + 1,
  );
});
