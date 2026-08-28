import {
  expect,
  test,
  chromium,
  type Page,
  type APIRequestContext,
} from "@playwright/test";

/**
 * Voice input in the assistant drawer.
 *
 * The microphone is a real one — Chromium's fake audio device — so the recorder actually runs,
 * but transcription is stubbed: a speech-to-text provider would need a key in CI and would not
 * be deterministic, and what needs testing is the wiring around it. The two behaviours that
 * matter are the ones an operator chooses between: a transcript lands in the box to review, or
 * it is sent straight away.
 *
 * The browser is launched per test rather than through the shared fixture because the fake
 * audio device is a launch argument.
 */

async function setSetting(
  request: APIRequestContext,
  key: string,
  value: unknown,
) {
  const res = await request.post(`/api/v1/setting/${key}`, {
    headers: { "Content-Type": "application/json" },
    // Double-encoded: the stored value is itself a JSON string. See aisettings.spec.ts.
    data: JSON.stringify(JSON.stringify(value)),
  });
  if (!res.ok()) throw new Error(`setting ${key} -> ${res.status()}`);
}

/** Chat on, voice on, and a speech-to-text endpoint configured so the mic is offered. */
async function enableVoice(request: APIRequestContext, autosend: boolean) {
  await setSetting(request, "ai_feature_chat", true);
  await setSetting(request, "ai_feature_voice", true);
  await setSetting(request, "ai_voice_autosend", autosend);
  await setSetting(request, "ai_stt_base_url", "http://127.0.0.1:9/v1");
  await setSetting(request, "ai_stt_model", "whisper-1");
}

async function withMicrophone(
  baseURL: string,
  body: (page: Page) => Promise<void>,
) {
  const browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
    ],
  });
  try {
    const context = await browser.newContext({
      baseURL,
      locale: "en-US",
      permissions: ["microphone"],
      serviceWorkers: "block",
    });
    await body(await context.newPage());
  } finally {
    await browser.close();
  }
}

const drawer = (page: Page) => page.getByRole("dialog", { name: "Assistant" });

async function openDrawer(page: Page) {
  await page.goto("/", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Ask the assistant" }).click();
  await expect(drawer(page)).toBeVisible();
}

/** Hold the mic button long enough for the recorder to capture something. */
async function holdMic(page: Page, ms = 900) {
  const mic = drawer(page).getByRole("button", { name: "Hold to talk" });
  await mic.hover();
  await page.mouse.down();
  await page.waitForTimeout(ms);
  await page.mouse.up();
}

test("the microphone is not offered until speech-to-text is configured", async ({
  request,
  baseURL,
}) => {
  // Voice enabled but no transcription endpoint: a mic here would 409 on every press.
  await setSetting(request, "ai_feature_chat", true);
  await setSetting(request, "ai_feature_voice", true);
  await setSetting(request, "ai_stt_base_url", "");
  await setSetting(request, "ai_stt_model", "");

  await withMicrophone(baseURL!, async (page) => {
    await openDrawer(page);
    // The drawer still works; only the mic is absent.
    await expect(drawer(page).getByRole("textbox")).toBeVisible();
    await expect(
      drawer(page).getByRole("button", { name: "Hold to talk" }),
    ).toHaveCount(0);
  });
});

test("a transcript lands in the box to review, by default", async ({
  request,
  baseURL,
}) => {
  // The default is deliberate: speech-to-text mangles vendor names, and a wrong word sent
  // straight to a tool-calling assistant is worse than one the user can fix first.
  await enableVoice(request, false);

  await withMicrophone(baseURL!, async (page) => {
    await page.route("**/api/v1/ai/transcribe", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ text: "how much PETG do I have" }),
      }),
    );
    await openDrawer(page);
    await holdMic(page);

    await expect(drawer(page).getByRole("textbox")).toHaveValue(
      "how much PETG do I have",
    );
    // Nothing was sent: the transcript is a draft until the user says so.
    await expect(drawer(page)).not.toContainText("Thinking");
  });
});

test("autosend sends the transcript without waiting to be reviewed", async ({
  request,
  baseURL,
}) => {
  await enableVoice(request, true);

  await withMicrophone(baseURL!, async (page) => {
    await page.route("**/api/v1/ai/transcribe", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ text: "what is low" }),
      }),
    );
    await page.route("**/api/v1/ai/chat", (route) =>
      route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream" },
        body: 'event: message\ndata: {"content":"Two filaments are low."}\n\nevent: done\ndata: {}\n\n',
      }),
    );
    await openDrawer(page);
    await holdMic(page);

    // The user's words appear as a turn, not as a draft.
    await expect(drawer(page)).toContainText("what is low");
    await expect(drawer(page)).toContainText("Two filaments are low.");
    await expect(drawer(page).getByRole("textbox")).toHaveValue("");
  });
});

test("a failed transcription is reported rather than silently dropped", async ({
  request,
  baseURL,
}) => {
  await enableVoice(request, false);

  await withMicrophone(baseURL!, async (page) => {
    await page.route("**/api/v1/ai/transcribe", (route) =>
      route.fulfill({
        status: 502,
        contentType: "application/json",
        body: "{}",
      }),
    );
    await openDrawer(page);
    await holdMic(page);

    await expect(
      drawer(page)
        .getByText(/microphone|could not/i)
        .first(),
    ).toBeVisible();
    // The composer has to come back, or one bad clip ends the conversation.
    await expect(drawer(page).getByRole("textbox")).toBeEnabled();
  });
});
