import { expect, test, type Page } from "@playwright/test";
import { measureSpool, seedSpool, spoolMeasurements } from "./helpers";

/**
 * The fork's weight-history chart on the spool inspector
 * (client_v2/src/lib/ng/components/WeightHistoryChart.svelte).
 *
 * The chart is drawn from the spool's own usage-event log, so every spool here is weighed
 * through the API rather than through the adjust panel: what is under test is the chart, not
 * the panel that happens to be one way of producing a measurement. Gross weights stay under
 * 1190 g (1000 g of filament on a 190 g spool) so each one is recorded as usage rather than
 * re-registering the spool at a new initial weight.
 */

const chart = (page: Page) => page.getByRole("img", { name: "Measured weight over time" });

async function openInspector(page: Page, spoolId: number) {
  await page.goto(`/?sel=spool:${spoolId}`, { waitUntil: "networkidle" });
  // The gauge is the block the chart sits directly under, so its presence means the inspector
  // has rendered and an absent chart below is a real absence rather than an unfinished load.
  await expect(page.locator(".insp .gauge")).toBeVisible();
}

test("charts a spool's measured weights once there are two of them", async ({ page, request }) => {
  const { spoolId } = await seedSpool(request, "WhChart", "Shelf W");
  await measureSpool(request, spoolId, 1150);
  await measureSpool(request, spoolId, 1100);
  expect(await spoolMeasurements(request, spoolId)).toHaveLength(2);

  await openInspector(page, spoolId);

  await expect(chart(page)).toBeVisible();
  // Two measurements, two plotted points, and the heavier one labelled on the axis.
  await expect(chart(page).locator("circle")).toHaveCount(2);
  await expect(chart(page).locator("text").first()).toHaveText("1150");
  // A falling series is ordinary consumption and must not raise the moisture hint.
  await expect(page.getByText(/may have absorbed moisture/)).toHaveCount(0);
});

test("shows no chart for a spool with a single measurement", async ({ page, request }) => {
  const { spoolId } = await seedSpool(request, "WhOne", "Shelf X");
  await measureSpool(request, spoolId, 1150);

  await openInspector(page, spoolId);

  await expect(chart(page)).toHaveCount(0);
});

test("draws the chart and the moisture hint when a weigh-in lands while the inspector is open", async ({
  page,
  request,
}) => {
  const { spoolId } = await seedSpool(request, "WhLive", "Shelf Y");
  await measureSpool(request, spoolId, 1100);

  await openInspector(page, spoolId);
  await expect(chart(page)).toHaveCount(0);

  // A spool that got heavier between weigh-ins: the chart appears without a reload, because the
  // backend broadcasts the spool update over the websocket the chart is subscribed to, and the
  // rise is flagged as possible moisture.
  await measureSpool(request, spoolId, 1150);

  await expect(chart(page)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/rose by 50\.0 g/)).toBeVisible();
});
