import {
  expect,
  test,
  type Page,
  type APIRequestContext,
} from "@playwright/test";

/**
 * The operator's AI panel (client_v2/src/lib/ng/components/AiSettings.svelte) and the two
 * surfaces it switches on.
 *
 * The panel is what decides whether any AI appears in this client at all, so what is tested
 * here is mostly refusal: nothing renders until it is enabled, and a feature cannot be enabled
 * before the thing it needs exists. Those are the paths a screenshot flatters, because a
 * half-configured assistant looks identical to a working one until someone presses it.
 */

/**
 * Write one server setting.
 *
 * The body is DOUBLE-encoded, which is not a quirk of this helper: a setting's stored value is
 * itself a JSON string, and the endpoint takes that string as its body -- so the request body
 * is the JSON encoding of the JSON encoding of the value. Single-encoding a string answers 400,
 * and single-encoding a boolean happens to work, which is exactly how you write a helper that
 * passes on the flags and fails on the URLs.
 */
async function setSetting(
  request: APIRequestContext,
  key: string,
  value: unknown,
) {
  const res = await request.post(`/api/v1/setting/${key}`, {
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify(JSON.stringify(value)),
  });
  if (!res.ok())
    throw new Error(`setting ${key} -> ${res.status()} ${await res.text()}`);
}

/** Put the server back to first-run, so each test states its own preconditions. */
async function resetAi(request: APIRequestContext) {
  for (const k of [
    "ai_feature_chat",
    "ai_feature_voice",
    "ai_feature_nl_search",
    "ai_voice_autosend",
  ]) {
    await setSetting(request, k, false);
  }
  for (const k of [
    "ai_base_url",
    "ai_model",
    "ai_stt_base_url",
    "ai_stt_model",
  ]) {
    await setSetting(request, k, "");
  }
}

/** The panel's own region. The General section has a "Base URL" too, so scoping is required. */
const panel = (page: Page) => page.getByRole("region", { name: "AI" });

/**
 * The whole SettingRow, not the text block inside it.
 *
 * The class test has to be exact. SettingRow nests `.row-main` (title and description) inside
 * `.row` (which also holds the control), and `contains(@class,'row')` matches BOTH -- picking
 * the inner one, which has the text but never the switch. That made "a blocked feature shows no
 * switch" pass against a locator that could not have found a switch either way.
 */
const featureRow = (page: Page, label: string) =>
  panel(page)
    .getByText(label, { exact: true })
    .locator(
      "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' row ')][1]",
    );

test.beforeEach(async ({ request }) => {
  await resetAi(request);
});

test("the panel explains a feature it cannot switch on yet", async ({
  page,
  request,
}) => {
  // With no endpoint saved, enabling chat would give a button that 409s on first use. The
  // reason is on the row rather than hidden behind a disabled control.
  await page.goto("/settings", { waitUntil: "networkidle" });

  const row = featureRow(page, "Chat assistant");
  await expect(row).toContainText(
    "Configure and save an endpoint and chat model first",
  );
  await expect(row.getByRole("switch")).toHaveCount(0);
});

test("saving an endpoint and model unblocks the features that needed them", async ({
  page,
}) => {
  await page.goto("/settings", { waitUntil: "networkidle" });

  await panel(page)
    .getByRole("textbox", { name: "AI endpoint URL", exact: true })
    .fill("http://localhost:11434/v1");
  // The model field is a plain input with a datalist, not a select.
  await panel(page)
    .getByRole("combobox", { name: "Chat model", exact: true })
    .fill("qwen3:8b");
  await panel(page).getByRole("button", { name: "Save" }).click();

  // The switch appearing IS the assertion: it is rendered only once nothing blocks it.
  await expect(
    featureRow(page, "Chat assistant").getByRole("switch"),
  ).toBeVisible();
});

test("voice stays blocked on speech-to-text, not on the chat provider", async ({
  page,
  request,
}) => {
  // Voice needs a transcription endpoint, which is a different setting from the chat one.
  // Blocking it on the wrong prerequisite would send the operator to the wrong field.
  await setSetting(request, "ai_base_url", "http://localhost:11434/v1");
  await setSetting(request, "ai_model", "qwen3:8b");
  await page.goto("/settings", { waitUntil: "networkidle" });

  const row = featureRow(page, "Voice input");
  await expect(row).toContainText("speech-to-text");
  await expect(row.getByRole("switch")).toHaveCount(0);

  await setSetting(request, "ai_stt_base_url", "http://localhost:8000/v1");
  await setSetting(request, "ai_stt_model", "whisper-1");
  await page.reload({ waitUntil: "networkidle" });
  await expect(
    featureRow(page, "Voice input").getByRole("switch"),
  ).toBeVisible();
});

test("a feature this client has no UI for is offered anyway, and says so", async ({
  page,
  request,
}) => {
  // The settings are server-wide: switching photo intake on here legitimately enables it in the
  // classic client. Blocking it would be this client deciding for the other one.
  await setSetting(request, "ai_base_url", "http://localhost:11434/v1");
  await setSetting(request, "ai_model", "qwen3:8b");
  await page.goto("/settings", { waitUntil: "networkidle" });

  await expect(featureRow(page, "MCP server")).toContainText(
    "classic interface",
  );
  await expect(
    featureRow(page, "MCP server").getByRole("switch"),
  ).toBeVisible();
});

test("the API key field never shows a stored key", async ({
  page,
  request,
}) => {
  // The server returns only whether one exists. A field that appeared to hold the key would be
  // showing something it does not have.
  await setSetting(request, "ai_base_url", "http://localhost:11434/v1");
  await page.goto("/settings", { waitUntil: "networkidle" });

  const key = panel(page).getByRole("textbox", {
    name: "API key",
    exact: true,
  });
  await expect(key).toHaveValue("");
});

test("its fields do not collide with the settings page's own labels", async ({
  page,
}) => {
  // This panel adds inputs to a page that already has a "Base URL" -- the server's own. Naming
  // them identically is ambiguous to anyone navigating by label, and it takes any page-wide
  // query for that name down with a strict-mode violation. That is not hypothetical: it broke
  // upstream's own settings spec, which is the only reason it was noticed.
  await page.goto("/settings", { waitUntil: "networkidle" });

  await expect(page.getByLabel("Base URL")).toHaveCount(1);
  await expect(page.getByLabel("Currency")).toHaveCount(1);
  await expect(page.getByLabel("Round prices")).toHaveCount(1);
});
