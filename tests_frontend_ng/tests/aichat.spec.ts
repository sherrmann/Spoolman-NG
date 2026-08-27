import { expect, test, type Page, type APIRequestContext } from "@playwright/test";

/**
 * The assistant drawer (client_v2/src/lib/ng/components/AiChatDrawer.svelte).
 *
 * The chat stream is STUBBED rather than driven by a real model: a model would make these tests
 * non-deterministic and require an API key in CI, and what needs testing here is not the model
 * but the protocol around it -- SSE frames arriving, a mutation stopping the stream, the
 * transcript being handed back verbatim, the composer re-opening afterwards. Intercepting
 * `/api/v1/ai/chat` lets a whole conversation, including a confirmed write, run in a browser.
 *
 * The gating tests are the exception and use the real endpoints, because "renders nothing at
 * all" is a claim about the real settings flag and would be worthless against a stub.
 */

/** One `event:`/`data:` frame in the shape spoolman/aichat.py emits. */
const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

async function setChatFlag(request: APIRequestContext, on: boolean) {
  const res = await request.post("/api/v1/setting/ai_feature_chat", {
    headers: { "Content-Type": "application/json" },
    data: JSON.stringify(String(on)),
  });
  if (!res.ok()) throw new Error(`setting ai_feature_chat -> ${res.status()}`);
}

const drawer = (page: Page) => page.getByRole("dialog", { name: "Assistant" });
const launcher = (page: Page) => page.getByRole("button", { name: "Ask the assistant" });

/** Serve a scripted stream, and capture what the client posted for each turn. */
async function stubChat(page: Page, turns: string[][]) {
  const posted: Record<string, unknown>[] = [];
  let turn = 0;
  await page.route("**/api/v1/ai/chat", async (route) => {
    posted.push(JSON.parse(route.request().postData() ?? "{}"));
    const body = (turns[turn] ?? []).join("");
    turn += 1;
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
      body,
    });
  });
  return posted;
}

async function open(page: Page) {
  await page.goto("/", { waitUntil: "networkidle" });
  await launcher(page).click();
  await expect(drawer(page)).toBeVisible();
}

test("renders nothing at all while the feature is switched off", async ({ page, request }) => {
  // Not a disabled button and not a placeholder: the endpoint 404s while the flag is off, so a
  // visible control would be one that cannot work. This is the fork's stated rule for every AI
  // surface, and the only test here that must run against the real setting.
  await setChatFlag(request, false);
  await page.goto("/", { waitUntil: "networkidle" });
  await expect(launcher(page)).toHaveCount(0);
});

test("appears once an operator switches it on", async ({ page, request }) => {
  await setChatFlag(request, true);
  await page.goto("/", { waitUntil: "networkidle" });
  await expect(launcher(page)).toBeVisible();
});

test("an unconfigured server says so instead of failing vaguely", async ({ page, request }) => {
  // This runs against the REAL endpoint, which answers 409 because no model is configured. The
  // three pre-stream statuses each need their own instruction, and "an administrator can set
  // one" is only correct for this one.
  await setChatFlag(request, true);
  await open(page);

  await drawer(page).getByRole("textbox").fill("how much PETG?");
  await drawer(page).getByRole("button", { name: "Send" }).click();

  await expect(drawer(page)).toContainText("no AI endpoint configured");
  // A failed turn must not leave the composer disabled forever.
  await expect(drawer(page).getByRole("textbox")).toBeEnabled();
});

test("shows the tools it ran and the answer it gave", async ({ page, request }) => {
  await setChatFlag(request, true);
  await stubChat(page, [
    [
      frame("tool", { name: "find_spools", summary: "Found 3 spool(s), 1200 g remaining." }),
      frame("message", { content: "You have about 1.2 kg of PETG." }),
      frame("done", {}),
    ],
  ]);
  await open(page);

  await drawer(page).getByRole("textbox").fill("how much PETG?");
  await drawer(page).getByRole("button", { name: "Send" }).click();

  // The tool line is what keeps the answer from being unexplained.
  await expect(drawer(page)).toContainText("Found 3 spool(s), 1200 g remaining.");
  await expect(drawer(page)).toContainText("You have about 1.2 kg of PETG.");
});

test("a mutation stops for approval and only then reports what it did", async ({ page, request }) => {
  await setChatFlag(request, true);
  const serverConvo = [
    { role: "user", content: "move spool 4 to shelf B" },
    { role: "assistant", tool_calls: [{ id: "call_1", function: { name: "update_spool" } }] },
  ];
  const posted = await stubChat(page, [
    [
      frame("confirm", {
        messages: serverConvo,
        cards: [
          {
            tool_call_id: "call_1",
            tool: "update_spool",
            title: "Update spool #4",
            summary: "Move it to Shelf B",
            before: { location: "Shelf A" },
            after: { location: "Shelf B" },
            destructive: false,
          },
        ],
      }),
      frame("done", {}),
    ],
    [
      frame("executed", { cards: [{ tool: "update_spool", summary: "Moved to Shelf B", undo: null }] }),
      frame("message", { content: "Done." }),
      frame("done", {}),
    ],
  ]);
  await open(page);

  await drawer(page).getByRole("textbox").fill("move spool 4 to shelf B");
  await drawer(page).getByRole("button", { name: "Send" }).click();

  // The preview has to name the change, old and new, or approving it is approving nothing.
  await expect(drawer(page)).toContainText("Update spool #4");
  await expect(drawer(page)).toContainText("Shelf A");
  await expect(drawer(page)).toContainText("Shelf B");
  // Nothing has run yet, and the composer stays shut while a write is held open.
  await expect(drawer(page)).not.toContainText("Moved to Shelf B");
  await expect(drawer(page).getByRole("textbox")).toBeDisabled();

  await drawer(page).getByRole("button", { name: "Confirm" }).click();
  await expect(drawer(page)).toContainText("Moved to Shelf B");
  await expect(drawer(page).getByRole("textbox")).toBeEnabled();

  // The decisive assertion: the second request must carry the transcript the confirm frame
  // handed back, verbatim. Re-posting our own would ask the model to decide again, and the
  // user's approval would land on a mutation nobody previewed.
  expect(posted).toHaveLength(2);
  expect(posted[1].decision).toBe("confirm");
  expect(posted[1].messages).toEqual(serverConvo);
});

test("declining a mutation is recorded rather than silently dropped", async ({ page, request }) => {
  await setChatFlag(request, true);
  const posted = await stubChat(page, [
    [
      frame("confirm", {
        messages: [{ role: "user", content: "delete it" }],
        cards: [
          {
            tool: "delete_spool",
            title: "Delete spool #4",
            summary: "This removes it",
            before: { id: 4 },
            after: {},
            destructive: true,
          },
        ],
      }),
      frame("done", {}),
    ],
    [frame("cancelled", {}), frame("done", {})],
  ]);
  await open(page);

  await drawer(page).getByRole("textbox").fill("delete spool 4");
  await drawer(page).getByRole("button", { name: "Send" }).click();

  // A destructive card has to say so before the button is pressed, not after.
  await expect(drawer(page)).toContainText("Cannot be undone");

  await drawer(page).getByRole("button", { name: "Cancel" }).click();
  await expect(drawer(page)).toContainText("Cancelled");
  expect(posted[1].decision).toBe("cancel");
});

test("closing mid-turn abandons the request rather than leaving it running", async ({
  page,
  request,
}) => {
  await setChatFlag(request, true);
  // Deliberately never fulfilled, so the turn is still in flight when the drawer closes.
  await page.route("**/api/v1/ai/chat", () => {});
  await open(page);

  await drawer(page).getByRole("textbox").fill("something slow");
  await drawer(page).getByRole("button", { name: "Send" }).click();
  await expect(drawer(page).getByRole("textbox")).toBeDisabled();

  await page.keyboard.press("Escape");
  await expect(drawer(page)).toBeHidden();
  // Reopening starts a fresh conversation with a working composer, which is only true if the
  // abandoned turn is not still holding the state.
  await launcher(page).click();
  await expect(drawer(page).getByRole("textbox")).toBeEnabled();
});
