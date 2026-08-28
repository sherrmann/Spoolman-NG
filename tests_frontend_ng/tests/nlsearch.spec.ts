import {
  expect,
  test,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { seedSpool, unique } from "./helpers";

/**
 * Natural-language search (client_v2/src/lib/ng/components/NlSearchButton.svelte).
 *
 * The translation itself is stubbed: it needs a model, and what matters here is not whether the
 * model understood the sentence but whether its answer becomes the Library's own filter state.
 * The mapping is unit-tested in nlSearch.test.ts; these tests are about the wiring and about
 * the reporting, which is the part with no equivalent in the React client — this Library cannot
 * express free text or colour, and a search that silently arrives half applied looks like a bad
 * match rather than a partial one.
 */

async function setFlag(request: APIRequestContext, on: boolean) {
  const res = await request.post("/api/v1/setting/ai_feature_nl_search", {
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify(JSON.stringify(on)),
  });
  if (!res.ok()) throw new Error(`flag -> ${res.status()}`);
}

const trigger = (page: Page) =>
  page.getByRole("button", { name: "Search with natural language" });

async function stub(page: Page, body: unknown) {
  await page.route("**/api/v1/ai/nl-search", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    }),
  );
}

async function ask(page: Page, text: string) {
  await trigger(page).click();
  const box = page.getByRole("dialog", {
    name: "Search with natural language",
  });
  await box.getByRole("textbox").fill(text);
  await box.getByRole("button", { name: "Search" }).click();
}

test("stays invisible until an operator enables it", async ({
  page,
  request,
}) => {
  await setFlag(request, false);
  await page.goto("/", { waitUntil: "networkidle" });
  await expect(trigger(page)).toHaveCount(0);
});

test("a translated search becomes ordinary, editable filter chips", async ({
  page,
  request,
}) => {
  // The whole design: this never becomes a separate "AI search mode" the user has to leave.
  // What comes back is the same chips they could have picked by hand.
  await setFlag(request, true);
  const { spoolId } = await seedSpool(request, "NlSearch", unique("Shelf"));
  expect(spoolId).toBeGreaterThan(0);
  await stub(page, {
    filters: [{ field: "filament.material", values: ["PLA"] }],
  });

  await page.goto("/", { waitUntil: "networkidle" });
  await ask(page, "show me the PLA");

  // The chip is the assertion — it is removable, which a bespoke result list would not be.
  await expect(page.getByRole("button", { name: /PLA/ }).first()).toBeVisible();
  await expect(page).toHaveURL(/[?&]f=/);
});

test("says so when part of the search could not be applied here", async ({
  page,
  request,
}) => {
  // This Library has no free-text parameter and no colour filter. Dropping those silently is
  // the failure worth guarding: the user sees results far broader than they asked for and has
  // no way to tell why.
  await setFlag(request, true);
  await stub(page, {
    filters: [{ field: "filament.material", values: ["PETG"] }],
    search: "matte",
    color_hex: "000000",
  });

  await page.goto("/", { waitUntil: "networkidle" });
  await ask(page, "matte black PETG");

  await expect(page.getByText(/was left out/i).first()).toBeVisible();
});

test("says plainly when nothing matched a filter", async ({
  page,
  request,
}) => {
  // An empty result with no message is the outcome most likely to be read as a broken feature.
  await setFlag(request, true);
  await stub(page, { filters: [], search: "something unmatchable" });

  await page.goto("/", { waitUntil: "networkidle" });
  await ask(page, "something unmatchable");

  await expect(page.getByText(/Nothing in that search matched/i)).toBeVisible();
});

test("keeps the popover open on failure so the typed text is not lost", async ({
  page,
  request,
}) => {
  await setFlag(request, true);
  await page.route("**/api/v1/ai/nl-search", (route) =>
    route.fulfill({ status: 500, body: "{}" }),
  );

  await page.goto("/", { waitUntil: "networkidle" });
  await ask(page, "black PETG");

  const box = page.getByRole("dialog", {
    name: "Search with natural language",
  });
  await expect(box).toBeVisible();
  await expect(box).toContainText("could not be translated");
  await expect(box.getByRole("textbox")).toHaveValue("black PETG");
});
