import dayjs from "dayjs";
import localizedFormat from "dayjs/plugin/localizedFormat.js";
import { APP_BASE_URL } from "../constants";
import { expect, test } from "../fixtures";

// #298 orders/low-stock redesign journeys: the merged per-filament Low Stock dashboard tab + full
// page + always-visible nav (Tasks 8-9), US1 mark-as-ordered (Task 10), US2 bulk order (Task 10),
// and US3 split arrival + the spool-create banner (Task 11). Follows print-dialog.spec.ts's
// conventions: seed state via `request` against the real backend, click antd controls by their
// visible text, and never touch the real Print pipeline (not applicable here).

dayjs.extend(localizedFormat);

type APIRequestContext = import("@playwright/test").APIRequestContext;

async function seedFilament(
  request: APIRequestContext,
  name: string,
  extra: Record<string, unknown> = {},
): Promise<number> {
  const fil = await (
    await request.post(`${APP_BASE_URL}/api/v1/filament`, {
      data: { name, density: 1.24, diameter: 1.75, weight: 1000, ...extra },
    })
  ).json();
  return fil.id as number;
}

async function seedSpool(request: APIRequestContext, filamentId: number, usedWeight: number): Promise<number> {
  const spool = await (
    await request.post(`${APP_BASE_URL}/api/v1/spool`, {
      data: { filament_id: filamentId, used_weight: usedWeight },
    })
  ).json();
  return spool.id as number;
}

async function seedOrder(
  request: APIRequestContext,
  lines: { filament_id: number; quantity: number }[],
  extra: Record<string, unknown> = {},
): Promise<{ id: number; lines: { id: number; quantity: number }[] }> {
  return await (await request.post(`${APP_BASE_URL}/api/v1/order`, { data: { lines, ...extra } })).json();
}

test.describe("orders and low-stock journeys", () => {
  test("merged low-stock sections + nav: a single Low Stock tab, no Shopping List tab, both nav items always visible", async ({
    page,
    request,
  }) => {
    const ts = Date.now();
    // Below its own threshold (300 remaining <= 500 explicit) — lands in the "explicit" section.
    const explicitId = await seedFilament(request, `LSExplicit ${ts}`, { low_stock_threshold: 500 });
    await seedSpool(request, explicitId, 700);
    // No threshold, but below the 200 g global fallback (100 remaining) — the "fallback" section.
    const fallbackId = await seedFilament(request, `LSFallback ${ts}`);
    await seedSpool(request, fallbackId, 900);

    await page.goto(`${APP_BASE_URL}/`);
    // Force the tab active regardless of which query (spools vs. filaments) settles first — the
    // dashboard's Tabs only reads hasLowStock for its *initial* defaultActiveKey (#298 known race).
    await page.getByRole("tab", { name: "Low Stock" }).click();

    await expect(page.getByRole("tab", { name: "Low Stock" })).toHaveCount(1);
    await expect(page.getByRole("tab", { name: "Shopping List" })).toHaveCount(0);
    await expect(page.getByText("Below your set threshold")).toBeVisible();
    await expect(page.getByText("Below the 200 g default")).toBeVisible();

    // Always-visible nav (US5 amended) — present with or without any low-stock filament. Exact
    // names disambiguate from the KPI cards (e.g. the "Total Stock" card's "N LOW STOCK" footer).
    await expect(page.getByRole("link", { name: "Low Stock", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Orders", exact: true })).toBeVisible();
  });

  test("mark-as-ordered (US1): fills shop + quantity/price, defaults the order date to today, and shows the Ordered pill", async ({
    page,
    request,
  }) => {
    const ts = Date.now();
    const name = `MarkOrdered ${ts}`;
    const filamentId = await seedFilament(request, name, { low_stock_threshold: 500 });
    await seedSpool(request, filamentId, 700); // remaining 300 <= 500

    await page.goto(`${APP_BASE_URL}/lowstock`);
    const row = page.locator(".lowstock-list .ant-card", { hasText: name });
    await row.getByRole("button", { name: "Mark as ordered" }).click();

    const modal = page.locator(".ant-modal-content").last();
    const dialogTitle = `Mark "${name}" as ordered`;
    await expect(modal.getByText(dialogTitle)).toBeVisible();

    // Shop AutoComplete: typing a brand-new name creates it inline on submit. Its placeholder is a
    // decorative span rather than a native `placeholder` attribute, so target it by role instead.
    await modal.getByRole("combobox", { name: "Shop" }).fill("Acme Filaments");

    // Order-date DatePicker defaults to today (spec amendment de57697), backdatable but untouched here.
    const todayLabel = dayjs().format("L");
    await expect(modal.locator(".ant-picker input")).toHaveValue(todayLabel);

    await modal.locator(".ant-form-item", { hasText: "Quantity" }).getByRole("spinbutton").fill("2");
    await modal.locator(".ant-form-item", { hasText: "Price / spool" }).getByRole("spinbutton").fill("19.99");

    await modal.getByRole("button", { name: "Mark as ordered" }).click();
    await expect(page.getByText(dialogTitle)).toBeHidden();

    // The calm blue "Ordered · today · <shop>" pill replaces the per-row action button.
    await expect(row.getByText(/Ordered.*Acme Filaments/)).toBeVisible();
    await expect(row.getByRole("button", { name: "Mark as ordered" })).toHaveCount(0);

    const filResp = await (await request.get(`${APP_BASE_URL}/api/v1/filament/${filamentId}`)).json();
    expect(filResp.on_order?.order_id).toBeGreaterThan(0);
  });

  test("bulk order (US2): multi-select two rows, create one order, and both rows get the Ordered pill", async ({
    page,
    request,
  }) => {
    const ts = Date.now();
    const nameA = `BulkA ${ts}`;
    const nameB = `BulkB ${ts}`;
    const filA = await seedFilament(request, nameA, { low_stock_threshold: 500 });
    await seedSpool(request, filA, 700); // remaining 300
    const filB = await seedFilament(request, nameB);
    await seedSpool(request, filB, 900); // remaining 100 (fallback)

    await page.goto(`${APP_BASE_URL}/lowstock`);
    await page.getByLabel(nameA).click();
    await page.getByLabel(nameB).click();

    await page.getByRole("button", { name: "Create order" }).click();

    const modal = page.locator(".ant-modal-content").last();
    const dialogTitle = "Create order — 2 selected";
    await expect(modal.getByText(dialogTitle)).toBeVisible();

    const shopName = `Bulk Shop ${ts}`;
    await modal.getByRole("combobox", { name: "Shop" }).fill(shopName);
    await modal.locator("tr", { hasText: nameA }).getByRole("spinbutton").fill("3");
    await modal.locator("tr", { hasText: nameB }).getByRole("spinbutton").fill("2");

    await modal.getByRole("button", { name: "Create order" }).click();
    await expect(page.getByText(dialogTitle)).toBeHidden();

    // The Orders page is always in the nav (US5) and lists the new order summarising both filaments.
    await page.goto(`${APP_BASE_URL}/orders`);
    const orderRow = page.locator("tr.ant-table-row", { hasText: shopName });
    await expect(orderRow.getByText("2 filaments")).toBeVisible();
    await expect(orderRow.getByText("Open — 5 outstanding")).toBeVisible();

    await page.goto(`${APP_BASE_URL}/lowstock`);
    await expect(page.locator(".lowstock-list .ant-card", { hasText: nameA }).getByText(/Ordered/)).toBeVisible();
    await expect(page.locator(".lowstock-list .ant-card", { hasText: nameB }).getByText(/Ordered/)).toBeVisible();
  });

  test("split arrival (US3): a partial delivery keeps the order Open, and the spool-create banner offers to finish it", async ({
    page,
    request,
  }) => {
    const ts = Date.now();
    const name = `SplitArrive ${ts}`;
    const filamentId = await seedFilament(request, name);
    const order = await seedOrder(request, [{ filament_id: filamentId, quantity: 4 }]);
    const orderId = order.id;
    // No order_number set — exercises the numberless-order fallback (Task 11 review carry-over:
    // arriveModal's orderLabel must render a single "#", not "##").
    const numberLabel = `#${orderId}`;

    await page.goto(`${APP_BASE_URL}/orders`);
    const orderRow = page.locator("tr.ant-table-row").filter({ has: page.getByText(numberLabel, { exact: true }) });
    await orderRow.getByRole("button", { name: "Arrived…" }).click();

    const modal = page.locator(".ant-modal-content").last();
    const dialogTitle = `What arrived from order ${numberLabel}?`;
    await expect(modal.getByText(dialogTitle)).toBeVisible();
    await expect(modal.getByText(`What arrived from order #${numberLabel}?`)).toHaveCount(0);

    // Deliver 2 of the 4 ordered — splits the line; create_spools stays on (default).
    await modal.getByRole("spinbutton").fill("2");
    await expect(modal.getByText("2 will arrive, 2 stay on order")).toBeVisible();

    await modal.getByRole("button", { name: "Mark arrived" }).click();
    await expect(page.getByText(dialogTitle)).toBeHidden();

    const spoolsResp = await (await request.get(`${APP_BASE_URL}/api/v1/spool?filament_id=${filamentId}`)).json();
    expect(spoolsResp.length).toBe(2);

    const refreshedRow = page.locator("tr.ant-table-row").filter({ has: page.getByText(numberLabel, { exact: true }) });
    await expect(refreshedRow.getByText("2 of 4 arrived")).toBeVisible();
    await expect(refreshedRow.getByText("Open — 2 outstanding")).toBeVisible();

    // The spool-create banner offers to finish the still-outstanding line from here.
    await page.goto(`${APP_BASE_URL}/spool/create?filament_id=${filamentId}`);
    await expect(page.getByText(`This filament is on order (order ${numberLabel})`)).toBeVisible();
  });

  test("order details modal (gate-feedback item #5): the row expander is gone, clicking the order # opens an editable modal (not a new tab), and editing a line's quantity updates the lines summary; delete is API-asserted", async ({
    page,
    request,
  }) => {
    const ts = Date.now();
    const nameA = `DetailsA ${ts}`;
    const nameB = `DetailsB ${ts}`;
    const filA = await seedFilament(request, nameA);
    const filB = await seedFilament(request, nameB);
    const orderUrl = "https://example.com/orders/4711";
    const order = await seedOrder(
      request,
      [
        { filament_id: filA, quantity: 2 },
        { filament_id: filB, quantity: 3 },
      ],
      { order_number: "4711", url: orderUrl },
    );
    // The seeded order has its own order_number, so the cell shows that instead of the "#id"
    // fallback (that fallback is exercised by the split-arrival test above).
    const numberLabel = "4711";

    await page.goto(`${APP_BASE_URL}/orders`);
    const orderRow = page.locator("tr.ant-table-row").filter({ has: page.getByText(numberLabel, { exact: true }) });
    // Gate-feedback item #4: the antd Table "+" row expander is gone entirely.
    await expect(orderRow.locator(".ant-table-row-expand-icon")).toHaveCount(0);
    await expect(orderRow.getByText("0 of 5 arrived")).toBeVisible();

    // Gate-feedback (order-link click conflict): the order # cell used to also be an
    // `<a target="_blank">` when the order carried a URL, so clicking it opened a new tab *and*
    // the details modal. It's plain text now — clicking it opens only the modal, and no second
    // page/tab appears in the browser context.
    await orderRow.getByText(numberLabel, { exact: true }).click();
    expect(page.context().pages()).toHaveLength(1);

    const modal = page.locator(".ant-modal-content").last();
    const dialogTitle = `Order ${numberLabel}`;
    await expect(modal.getByText(dialogTitle)).toBeVisible();

    // The modal is the one place the order's URL is a link now.
    const modalLink = modal.locator(".order-details-link a");
    await expect(modalLink).toHaveAttribute("href", orderUrl);
    await expect(modalLink).toHaveText(orderUrl);

    // Both lines are still outstanding, so both show editable quantity/price inputs. Bump the
    // first line's (nameA, quantity 2) delivered count up to 6 — the arrived line case is covered
    // by the split-arrival test above (buildEditedLines's read-only path is unit-tested directly).
    await modal.locator(".order-details-line", { hasText: nameA }).getByRole("spinbutton").first().fill("6");
    await modal.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText(dialogTitle)).toBeHidden();

    // 6 (edited) + 3 (untouched) = 9 total, still nothing arrived.
    const refreshedRow = page.locator("tr.ant-table-row").filter({ has: page.getByText(numberLabel, { exact: true }) });
    await expect(refreshedRow.getByText("0 of 9 arrived")).toBeVisible();

    // Delete + its lines-cascade is asserted directly against the API rather than through the
    // confirm-dialog UI, per the gate feedback.
    const deleteResp = await request.delete(`${APP_BASE_URL}/api/v1/order/${order.id}`);
    expect(deleteResp.ok()).toBeTruthy();
    const remainingOrders: { id: number }[] = await (await request.get(`${APP_BASE_URL}/api/v1/order`)).json();
    expect(remainingOrders.some((o) => o.id === order.id)).toBe(false);
  });
});
