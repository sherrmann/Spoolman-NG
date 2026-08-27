import { expect, test } from "@playwright/test";

/**
 * The Help page (client_v2/src/routes/help/).
 *
 * Its whole copy is one message carrying <Trans>-style markup, parsed at runtime by
 * $lib/ng/trans. The failure mode that parser exists to prevent is silent and total: render
 * the string as-is and the page fills with visible `<p>` and `<filamentCreateLink>` tags, which
 * no typecheck or unit test would notice. So the first assertion here is simply that no tag
 * reaches the reader.
 */

test("renders the help copy without leaking its markup", async ({ page }) => {
  await page.goto("/help", { waitUntil: "networkidle" });

  const body = await page.evaluate(() => document.body.innerText);
  expect(body, "a raw tag reached the page").not.toMatch(
    /<\/?(p|title|itemsHelp|filamentCreateLink|spoolCreateLink|vendorCreateLink|readmeLink)/,
  );
  // ...and the prose itself survived the parse rather than being dropped with the tags.
  expect(body).toContain("Spoolman holds 3 different types of data");
});

test("explains all three entity types", async ({ page }) => {
  await page.goto("/help", { waitUntil: "networkidle" });
  // The <itemsHelp/> placeholder, which the parser reports and the page renders as this list.
  for (const blurb of [
    /Brands of filament/i,
    /Individual physical spools/i,
    /companies that make the filament/i,
  ]) {
    await expect(page.getByText(blurb)).toBeVisible();
  }
});

test("the inline links point somewhere real", async ({ page }) => {
  await page.goto("/help", { waitUntil: "networkidle" });

  // This client has no /filament/create route -- creation happens in modals -- so each link
  // goes to the Library view where that entity is made. A link rendered as bare text would
  // mean the parser found a tag name the page has no target for.
  await expect(page.getByRole("link", { name: "Filament", exact: true })).toHaveAttribute(
    "href",
    /\/$|\/\?/,
  );
  await expect(page.getByRole("link", { name: "Spool", exact: true })).toHaveAttribute(
    "href",
    /group=none/,
  );
  await expect(page.getByRole("link", { name: "Manufacturer", exact: true })).toHaveAttribute(
    "href",
    /group=vendor/,
  );
  await expect(page.getByRole("link", { name: /Spoolman README/i })).toHaveAttribute(
    "href",
    /^https:\/\/github\.com\//,
  );
});

test("the home page's help link now resolves here", async ({ page }) => {
  // home.description names a <helpPageLink> that had no route to point at until this page
  // existed; the home page rendered its text unlinked. Both now use the same parser.
  await page.goto("/home", { waitUntil: "networkidle" });
  await page.locator('a[href$="/help"]').first().click();
  await expect(page).toHaveURL(/\/help$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/help/i);
});

test("the page scrolls inside the app shell rather than overflowing it", async ({ page }) => {
  await page.setViewportSize({ width: 700, height: 800 });
  await page.goto("/help", { waitUntil: "networkidle" });
  const { docScroll, viewport } = await page.evaluate(() => ({
    docScroll: document.documentElement.scrollHeight,
    viewport: window.innerHeight,
  }));
  expect(docScroll, `the document grew to ${docScroll}px`).toBeLessThanOrEqual(viewport + 1);
});
