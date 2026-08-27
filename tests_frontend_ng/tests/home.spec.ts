import { expect, test, type ConsoleMessage, type Page, type Request } from "@playwright/test";
import { apiCounts, seedInventory, type Seeded } from "./helpers";

/**
 * The fork's Home dashboard (client_v2/src/routes/home/).
 *
 * These assertions are chosen from what actually broke, not from what is easy to assert. The
 * page shipped once with a missing `scroll-y` class on its root: svelte-check, eslint, prettier
 * and 344 unit tests all passed, and it was only visible in a browser at a short viewport. The
 * overflow test at the bottom is the guard for that whole class of defect.
 */

let seeded: Seeded;

test.beforeAll(async ({ playwright, baseURL }) => {
  const api = await playwright.request.newContext({ baseURL });
  seeded = await seedInventory(api);
  await api.dispose();
});

/**
 * Fonts are fetched from Google's CDN, which a sandboxed or offline runner cannot reach. That
 * failure says nothing about this page, so it is the one exemption -- everything else, including
 * any 404 from a fork-only endpoint, must fail the test.
 *
 * Matched on the parsed hostname rather than as a substring of the URL. A substring test is
 * satisfied by any URL merely *containing* the text -- "https://example.test/?x=fonts.gstatic.com"
 * among them -- so it would quietly widen this exemption past the two hosts it is meant to cover
 * and could swallow a genuine failure the suite exists to catch.
 */
const FONT_HOSTS = new Set(["fonts.googleapis.com", "fonts.gstatic.com"]);

function isExternalFont(url: string): boolean {
  try {
    return FONT_HOSTS.has(new URL(url).hostname);
  } catch {
    // Console messages can carry an empty or non-absolute location; those are never the CDN.
    return false;
  }
}

function watchForFailures(page: Page) {
  const problems: string[] = [];
  page.on("console", (m: ConsoleMessage) => {
    if (m.type() === "error" && !isExternalFont(m.location().url)) problems.push(`console: ${m.text()}`);
  });
  page.on("requestfailed", (r: Request) => {
    if (!isExternalFont(r.url())) problems.push(`request failed: ${r.url()}`);
  });
  page.on("response", (r) => {
    if (r.status() >= 400 && !isExternalFont(r.url())) problems.push(`HTTP ${r.status()}: ${r.url()}`);
  });
  return problems;
}

async function openHome(page: Page) {
  await page.goto("/home", { waitUntil: "networkidle" });
  await expect(page.locator(".kpi-card").first()).toBeVisible();
}

test("renders the dashboard with counts that match the API", async ({ page, request }) => {
  const problems = watchForFailures(page);
  await openHome(page);

  await expect(page).toHaveTitle(/Home/);
  await expect(page.locator("nav a", { hasText: "Home" }).first()).toBeVisible();

  // Compared against the API rather than asserted non-empty: a card rendering a stale or
  // hardcoded number would still look populated in a screenshot.
  const counts = await apiCounts(request);
  const values = page.locator(".kpi-card .kpi-value");
  await expect(values.nth(0)).toHaveText(String(counts.spools));
  await expect(values.nth(1)).toHaveText(String(counts.filaments));
  await expect(values.nth(2)).toHaveText(String(counts.vendors));

  expect(problems, `page reported: ${problems.join(" | ")}`).toHaveLength(0);
});

test("low stock lists both sections and marks what is already on order", async ({ page }) => {
  await openHome(page);

  // Scoped to this run's own filaments rather than to ".pill" anywhere on the page: the suite
  // seeds on every run, so a shared instance accumulates rows and any global locator matches
  // whatever earlier runs left behind. Tying each assertion to the name we created keeps it
  // true regardless of what else is in the database.
  // By list-item role, not by an element or class: the row holds a stretched link plus real
  // controls, so it is a <li> whose <a> covers only the name. Roles are also what upstream's own
  // suite selects by -- this repo has no data-testid convention to borrow.
  const lowRow = (name: string) => page.getByRole("listitem").filter({ hasText: name }).first();

  // Both routes into "low" must render: a filament under its own threshold, and one under the
  // global fallback with no threshold of its own. They are computed by different branches.
  await expect(lowRow(seeded.explicitLowName)).toBeVisible();
  await expect(lowRow(seeded.fallbackLowName)).toBeVisible();

  // The ordered one carries the pill; without an open order the row looks identical to one
  // nobody has acted on, so this is the assertion that the order actually reached the page.
  await expect(lowRow(seeded.orderedName).locator(".pill")).toHaveText(/Ordered/);

  // And the un-ordered one must NOT carry it -- otherwise a pill rendered unconditionally
  // would satisfy the check above and mean nothing.
  await expect(lowRow(seeded.fallbackLowName).locator(".pill")).toHaveCount(0);
});

test("every tab switches and renders its panel", async ({ page }) => {
  const problems = watchForFailures(page);
  await openHome(page);

  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveCount(5);
  for (let i = 0; i < 5; i++) {
    await tabs.nth(i).click();
    await expect(tabs.nth(i)).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tabpanel")).toBeVisible();
  }

  // The Usage tab is the one backed by a fork-only endpoint (/stats/usage). A 404 there leaves
  // an empty panel that looks deliberate, so the failure watcher matters most here.
  expect(problems, `page reported: ${problems.join(" | ")}`).toHaveLength(0);
});

test("the page scrolls inside the app shell rather than overflowing it", async ({ page }) => {
  // The regression guard. The layout shell is height:100dvh and every page scrolls *within* it
  // (upstream's pages all carry `scroll-y`). If a page grows the document instead, the static
  // footer ends up painted across the page's own content -- which is exactly what shipped.
  //
  // Asserted behaviourally, on the document's own height, rather than by checking for a class
  // name: this keeps working if the class is ever renamed, and catches any other way a page
  // might break the same rule.
  await page.setViewportSize({ width: 700, height: 800 });
  await openHome(page);

  const { docScroll, viewport, pageScrolls } = await page.evaluate(() => {
    const el = document.querySelector(".page") as HTMLElement | null;
    return {
      docScroll: document.documentElement.scrollHeight,
      viewport: window.innerHeight,
      pageScrolls: el ? el.scrollHeight > el.clientHeight : false,
    };
  });

  expect(
    docScroll,
    `the document grew to ${docScroll}px against a ${viewport}px viewport, so the page is ` +
      `overflowing the shell instead of scrolling inside it`,
  ).toBeLessThanOrEqual(viewport + 1);

  // And the content really is taller than the pane -- otherwise the check above passes trivially
  // on a page that happens to be short, proving nothing.
  expect(pageScrolls, "seeded content should overflow the pane at 700x800").toBe(true);
});
