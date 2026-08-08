import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import en from "../../public/locales/en/common.json";
import type { ChatEvent, ChatTurnRequest } from "../utils/queryAI";

// The drawer is exercised hermetically: the SSE stream is behind streamChat, mocked here so
// we can script the agent's events. What we pin is the #362 contract — invisible unless the
// toggle is on, a mutation surfaces as a confirm-card, and Cancel re-posts with
// decision="cancel" (so nothing is executed).

const settingsMock = vi.fn<() => Record<string, { value: string }> | undefined>();
const statusMock = vi.fn<() => { stt_configured: boolean } | undefined>();
const streamChat = vi.fn<(body: ChatTurnRequest, onEvent: (e: ChatEvent) => void) => Promise<void>>();
const transcribeMock = vi.fn<(audio: Blob) => Promise<{ text: string }>>();

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useGetLocale: () => () => "en",
}));
vi.mock("react-router", () => ({ useLocation: () => ({ pathname: "/spool" }) }));
vi.mock("../utils/querySettings", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../utils/querySettings")>()),
  useGetSettings: () => ({ data: settingsMock() }),
}));
// The currency formatter reads a setting through react-query; the drawer is rendered bare here,
// so stub it with a predictable formatter instead of standing up a QueryClientProvider.
vi.mock("../utils/settings", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../utils/settings")>()),
  useCurrencyFormatter: () => ({ format: (value: number) => `€${value.toFixed(2)}` }),
}));
vi.mock("../utils/queryAI", () => ({
  streamChat: (body: ChatTurnRequest, onEvent: (e: ChatEvent) => void) => streamChat(body, onEvent),
  useChatAction: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAIStatus: () => ({ data: statusMock() }),
  useTranscribe: () => ({ mutateAsync: transcribeMock, isPending: false }),
  spoolListFilterLink: () => "/spool#filters=%5B%5D",
}));

import { ChatDrawer } from "./chatDrawer";

beforeEach(() => {
  vi.clearAllMocks();
  settingsMock.mockReturnValue({ ai_feature_chat: { value: "true" } });
  statusMock.mockReturnValue({ stt_configured: true });
});

describe("ChatDrawer (#362)", () => {
  it("renders nothing while the feature is disabled", () => {
    settingsMock.mockReturnValue({ ai_feature_chat: { value: "false" } });
    render(<ChatDrawer />);
    expect(screen.queryByLabelText("chat.open")).not.toBeInTheDocument();
  });

  it("shows the assistant button when enabled and opens the drawer", async () => {
    const user = userEvent.setup();
    render(<ChatDrawer />);
    await user.click(screen.getByLabelText("chat.open"));
    expect(screen.getByTestId("chat-empty")).toBeInTheDocument();
  });

  it("surfaces a mutation as a confirm-card and Cancel re-posts with decision=cancel", async () => {
    streamChat.mockImplementation(async (body, onEvent) => {
      if (body.decision === "cancel") {
        onEvent({ event: "message", data: { content: "Okay, I won't change anything." } });
        return;
      }
      onEvent({
        event: "confirm",
        data: {
          messages: [{ role: "user", content: "delete spool 1" }],
          cards: [
            {
              tool: "delete_spool",
              title: "Delete spool #1",
              summary: "This cannot be undone.",
              before: { id: 1 },
              after: {},
              destructive: true,
            },
          ],
        },
      });
    });

    const user = userEvent.setup();
    render(<ChatDrawer />);
    await user.click(screen.getByLabelText("chat.open"));
    await user.type(screen.getByTestId("chat-input"), "delete spool 1");
    await user.keyboard("{Enter}");

    // The confirm-card appears with the destructive marker and before/after values.
    await waitFor(() => expect(screen.getByText("Delete spool #1")).toBeInTheDocument());
    expect(screen.getByText("chat.confirm.destructive")).toBeInTheDocument();

    // Cancel re-posts the pending transcript with decision=cancel — nothing was executed.
    await user.click(screen.getByRole("button", { name: "chat.confirm.cancel" }));
    await waitFor(() =>
      expect(streamChat).toHaveBeenLastCalledWith(
        expect.objectContaining({ decision: "cancel" }),
        expect.any(Function),
      ),
    );
  });

  it("streams a plain answer for a question", async () => {
    streamChat.mockImplementation(async (_body, onEvent) => {
      onEvent({ event: "tool", data: { name: "find_spools", summary: "Found 1 spool, 1000 g remaining." } });
      onEvent({ event: "message", data: { content: "You have 1000 g of PETG." } });
    });

    const user = userEvent.setup();
    render(<ChatDrawer />);
    await user.click(screen.getByLabelText("chat.open"));
    await user.type(screen.getByTestId("chat-input"), "how much petg?");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(screen.getByText("You have 1000 g of PETG.")).toBeInTheDocument());
    expect(streamChat).toHaveBeenCalledWith(
      expect.objectContaining({ context: "Spools list", messages: [{ role: "user", content: "how much petg?" }] }),
      expect.any(Function),
    );
  });
});

// The redesigned confirm-card (#378). A card is what a user reads while deciding whether to
// destroy something, so what is pinned here is that it reads like the rest of the UI: human
// labels, formatted values, and — for an update — a diff instead of two blocks to compare by eye.
describe("ChatDrawer confirm-card rendering (#378)", () => {
  /** Resolve a dotted key against the real English catalog. */
  function lookupEnglish(key: string): unknown {
    return key.split(".").reduce<unknown>((node, part) => {
      if (node !== null && typeof node === "object" && part in node) {
        return (node as Record<string, unknown>)[part];
      }
      return undefined;
    }, en);
  }

  async function showCard(card: Record<string, unknown>) {
    streamChat.mockImplementation(async (_body, onEvent) => {
      onEvent({
        event: "confirm",
        data: { messages: [{ role: "user", content: "do it" }], cards: [card as never] },
      });
    });
    const user = userEvent.setup();
    const view = render(<ChatDrawer />);
    await user.click(screen.getByLabelText("chat.open"));
    await user.type(screen.getByTestId("chat-input"), "do it");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.getByTestId("chat-card-values")).toBeInTheDocument());
    return view;
  }

  const deleteOrderCard = {
    tool: "delete_order",
    title: "Delete order #2",
    summary: "The order and its lines are removed.",
    before: {
      id: 2,
      shop: "FilaShop",
      order_number: null,
      ordered_at: "2026-07-20 09:00",
      status: "open",
      outstanding_units: 5,
      lines: ["5 x Acme - PLA Meta"],
    },
    after: {},
    destructive: true,
  };

  it("labels every row with a translation instead of the schema key", async () => {
    await showCard(deleteOrderCard);
    expect(screen.getByTestId("chat-card-label-shop")).toHaveTextContent("orders.shop");
    expect(screen.getByTestId("chat-card-label-ordered_at")).toHaveTextContent("orders.ordered_at");
    expect(screen.getByTestId("chat-card-label-outstanding_units")).toHaveTextContent("orders.outstanding");
    expect(screen.getByTestId("chat-card-label-lines")).toHaveTextContent("orders.lines_summary_title");
    // Every visible label is a key the English catalog really defines — so no row can be showing
    // a raw schema key, nor the de-underscored fallback that only an unmapped field would hit.
    // (useTranslate is stubbed to the identity here, so a label renders as its catalog key.)
    for (const label of screen.getAllByTestId(/^chat-card-label-/)) {
      expect(lookupEnglish(label.textContent ?? ""), label.textContent ?? "").toBeTypeOf("string");
    }
  });

  it("formats each value by what it is", async () => {
    await showCard(deleteOrderCard);
    expect(screen.getByTestId("chat-card-value-ordered_at")).toHaveTextContent("July 20, 2026");
    expect(screen.getByTestId("chat-card-value-status")).toHaveTextContent("chat.confirm.status_open");
    expect(screen.getByTestId("chat-card-value-lines")).toHaveTextContent("5 x Acme - PLA Meta");
  });

  it("hides the rows that decide nothing about a delete", async () => {
    await showCard(deleteOrderCard);
    // The title already says #2, and an absent order number is not part of what is being deleted.
    expect(screen.queryByTestId("chat-card-value-id")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chat-card-value-order_number")).not.toBeInTheDocument();
    expect(screen.getByTestId("chat-card-values").textContent).not.toContain("∅");
  });

  it("hides an unset field and an uninformative default on a create", async () => {
    await showCard({
      tool: "create_spool",
      title: "Create spool",
      summary: "Adds one spool.",
      before: {},
      after: {
        filament: "Acme - PLA Meta",
        initial_weight_g: 1000.0,
        location: "Shelf A",
        lot_nr: null,
        archived: false,
      },
      destructive: false,
    });
    expect(screen.getByTestId("chat-card-value-initial_weight_g")).toHaveTextContent("1 kg");
    expect(screen.queryByTestId("chat-card-value-lot_nr")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chat-card-value-archived")).not.toBeInTheDocument();
  });

  it("renders an update as a diff of only the changed fields", async () => {
    await showCard({
      tool: "update_filament",
      title: "Update filament #1",
      summary: "Change colour and extruder temperature.",
      before: { color_hex: "FF0000CC", settings_extruder_temp: 210, comment: null, material: "PLA" },
      after: { color_hex: "0066CC", settings_extruder_temp: 215, comment: "winter batch", material: "PLA" },
      destructive: false,
    });

    // Unchanged fields are not part of the decision.
    expect(screen.queryByTestId("chat-card-value-material")).not.toBeInTheDocument();

    const temp = screen.getByTestId("chat-card-value-settings_extruder_temp");
    expect(temp).toHaveTextContent("210 °C");
    expect(temp).toHaveTextContent("215 °C");
    expect(temp.querySelector("del")).toHaveTextContent("210 °C");

    // The 8-digit before-colour keeps its hex; the 6-digit after-colour does not need one.
    const colour = screen.getByTestId("chat-card-value-color_hex");
    expect(colour).toHaveTextContent("chat.confirm.color.red (#FF0000CC)");
    expect(colour).toHaveTextContent("chat.confirm.color.blue");
    expect(screen.getAllByTestId("chat-card-swatch")).toHaveLength(2);

    // A field going from unset to set keeps the null visible — that IS the change.
    const comment = screen.getByTestId("chat-card-value-comment");
    expect(comment.querySelector("del")).toHaveTextContent("chat.confirm.not_set");
    expect(comment).toHaveTextContent("winter batch");
  });
});

// Minimal browser-API stubs jsdom lacks, so the push-to-talk flow can be exercised.
class MockMediaRecorder {
  state = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(public stream: unknown) {}
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

describe("ChatDrawer voice (#363)", () => {
  beforeEach(() => {
    settingsMock.mockReturnValue({ ai_feature_chat: { value: "true" }, ai_feature_voice: { value: "true" } });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) },
    });
    (globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = MockMediaRecorder;
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: { speak: vi.fn(), cancel: vi.fn() },
    });
    (globalThis as unknown as { SpeechSynthesisUtterance: unknown }).SpeechSynthesisUtterance = class {
      constructor(public text: string) {}
    };
  });

  afterEach(() => {
    delete (globalThis as unknown as { MediaRecorder?: unknown }).MediaRecorder;
  });

  async function openDrawer() {
    const user = userEvent.setup();
    render(<ChatDrawer />);
    await user.click(screen.getByLabelText("chat.open"));
    return user;
  }

  it("hides the mic when voice is disabled", async () => {
    settingsMock.mockReturnValue({ ai_feature_chat: { value: "true" } });
    await openDrawer();
    expect(screen.queryByTestId("chat-mic")).not.toBeInTheDocument();
  });

  it("hides the mic when no speech-to-text endpoint is configured", async () => {
    statusMock.mockReturnValue({ stt_configured: false });
    await openDrawer();
    expect(screen.queryByTestId("chat-mic")).not.toBeInTheDocument();
  });

  it("shows the mic when voice is enabled and STT is configured", async () => {
    await openDrawer();
    expect(screen.getByTestId("chat-mic")).toBeInTheDocument();
  });

  it("shows a speak-replies toggle when speechSynthesis is available", async () => {
    await openDrawer();
    expect(screen.getByTestId("chat-speak-toggle")).toBeInTheDocument();
  });

  it("hold-to-talk transcribes and drops the text into the input to review", async () => {
    transcribeMock.mockResolvedValue({ text: "log twenty grams on the orange Prusament" });
    await openDrawer();

    const mic = screen.getByTestId("chat-mic");
    fireEvent.pointerDown(mic);
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled());
    fireEvent.pointerUp(mic);

    // Transcribe-then-review: the recognised text lands editable in the input (not auto-sent).
    await waitFor(() =>
      expect(screen.getByTestId("chat-input")).toHaveValue("log twenty grams on the orange Prusament"),
    );
    expect(streamChat).not.toHaveBeenCalled();
  });
});
