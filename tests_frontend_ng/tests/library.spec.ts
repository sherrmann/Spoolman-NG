import { expect, test } from "@playwright/test";
import { seedFilament, unique } from "./helpers";

/**
 * Upstream's library list, checked for the one presentation defect this fork fixes inside it.
 *
 * A remaining weight with a decimal -- which any print integration reporting fractional grams
 * produces -- rendered as "987.5" on one line and "g" on the next: the column is a fixed 44px
 * and nothing stopped it wrapping (upstream issue 1124). The row is upstream's file, so this is
 * measured in a browser rather than asserted from the CSS: the fix is one declaration, and the
 * next subtree pull is exactly where it could quietly go missing again.
 */

test("a fractional remaining weight keeps its unit on the same line", async ({ page, request }) => {
  const location = unique("Shelf");
  const filament = await seedFilament(request, "Decimal");
  // 1000 g filament less 12.5 g used: the label the row must show is "987.5 g".
  const res = await request.post("/api/v1/spool", {
    data: { filament_id: filament.id, used_weight: 12.5, location },
  });
  expect(res.ok()).toBeTruthy();
  const spool = (await res.json()) as { id: number };

  // Narrow the list to this one spool so the row is on the first page whatever else the shared
  // instance holds.
  await page.goto(`/?f=location%3A${encodeURIComponent(location)}`, { waitUntil: "networkidle" });

  const row = page.locator("a.row", { hasText: `#${spool.id}` });
  await expect(row).toBeVisible();
  const rem = row.locator(".rem");
  await expect(rem).toHaveText("987.5 g");

  // One line of 11px text is well under 20px tall; a wrapped unit doubles it. The id column beside
  // it is the same font size and always a single line, so it is the reference height.
  const remBox = await rem.boundingBox();
  const idBox = await row.locator(".id").boundingBox();
  expect(remBox).not.toBeNull();
  expect(idBox).not.toBeNull();
  expect(remBox!.height).toBeLessThanOrEqual(idBox!.height + 1);
});
