import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AIChatResponse } from "../utils/queryAI";

// The chat flow is tested hermetically: the chat mutation, settings, locale and
// location are mocked; what is asserted is the contract of the UI - transcript
// round-tripping, confirm-gated writes, invisibility while disabled, and the
// push-to-talk capture flow (#363) against a stubbed MediaRecorder.

const chatMock = vi.fn();
const transcribeMock = vi.fn();
let chatFeature = "true";
let voiceFeature = "false";
let voiceAutoSend = "false";
let sttConfigured = false;

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useGetLocale: () => () => "en",
}));
vi.mock("react-router", () => ({ useLocation: () => ({ pathname: "/spool" }) }));
vi.mock("../utils/queryAI", () => ({
  useAIChat: () => ({ mutateAsync: chatMock, isPending: false }),
  useAIStatus: () => ({ data: { stt_configured: sttConfigured } }),
  useTranscribe: () => ({ mutateAsync: transcribeMock, isPending: false }),
}));
vi.mock("../utils/querySettings", () => ({
  useGetSettings: () => ({
    data: {
      ai_feature_chat: { value: chatFeature },
      ai_feature_voice: { value: voiceFeature },
      ai_voice_auto_send: { value: voiceAutoSend },
    },
  }),
}));

import ChatDrawer, { ChatPanel } from "./chatDrawer";

// Minimal MediaRecorder stand-in: jsdom has none. stop() synchronously delivers one
// chunk and the stop event, which is enough for the capture -> transcribe contract.
class FakeMediaRecorder {
  static created: FakeMediaRecorder[] = [];
  state = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(public stream: unknown) {
    FakeMediaRecorder.created.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob([new Uint8Array([1, 2, 3])], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

function stubRecordingSupport() {
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) },
    configurable: true,
  });
}

const textResponse = (reply: string, extra: Partial<AIChatResponse> = {}): AIChatResponse => ({
  messages: [
    { role: "user", content: "How much PLA?" },
    { role: "assistant", content: reply },
  ],
  reply,
  events: [],
  pending: null,
  stopped_reason: null,
  ...extra,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
  chatFeature = "true";
  voiceFeature = "false";
  voiceAutoSend = "false";
  sttConfigured = false;
  FakeMediaRecorder.created = [];
});

describe("ChatDrawer gating (#362)", () => {
  it("renders nothing while the chat feature is disabled", () => {
    chatFeature = "false";
    const { container } = render(<ChatDrawer />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the floating button when enabled and opens the drawer", async () => {
    const user = userEvent.setup();
    render(<ChatDrawer />);
    await user.click(screen.getByTestId("chat-fab"));
    expect(await screen.findByTestId("chat-panel")).toBeInTheDocument();
  });
});

describe("ChatPanel (#362)", () => {
  it("sends the transcript with context and renders reply plus tool events", async () => {
    chatMock.mockResolvedValue(
      textResponse("One spool with 750 g left.", {
        events: [{ tool: "find_spools", detail: "returned=1" }],
      }),
    );
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.type(screen.getByTestId("chat-input"), "How much PLA?");
    await user.click(screen.getByTestId("chat-send"));

    expect(await screen.findByText("One spool with 750 g left.")).toBeInTheDocument();
    expect(screen.getByText(/chat\.tools\.find_spools/)).toBeInTheDocument();
    const body = chatMock.mock.calls[0][0];
    expect(body.messages).toEqual([{ role: "user", content: "How much PLA?" }]);
    expect(body.context).toEqual({ page: "/spool", locale: "en" });
  });

  it("renders a confirm card for a pending write and executes it only on confirm", async () => {
    const wireMessages = [
      { role: "user", content: "Log 50 g" },
      { role: "assistant", content: null, tool_calls: [{ id: "call_w" }] },
    ];
    chatMock.mockResolvedValueOnce({
      messages: wireMessages,
      reply: null,
      events: [],
      pending: { id: "call_w", tool: "use_spool_filament", arguments: { spool_id: 3, use_weight_g: 50 } },
      stopped_reason: null,
    });
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.type(screen.getByTestId("chat-input"), "Log 50 g");
    await user.click(screen.getByTestId("chat-send"));

    const card = await screen.findByTestId("chat-pending");
    expect(card).toHaveTextContent("chat.tools.use_spool_filament");
    expect(card).toHaveTextContent("spool_id");
    expect(screen.getByTestId("chat-input")).toBeDisabled();

    chatMock.mockResolvedValueOnce(textResponse("Done - 50 g logged."));
    await user.click(screen.getByTestId("chat-confirm"));

    expect(await screen.findByText("Done - 50 g logged.")).toBeInTheDocument();
    expect(screen.getByText("chat.action_confirmed")).toBeInTheDocument();
    const resolveBody = chatMock.mock.calls[1][0];
    expect(resolveBody.resolve).toEqual({ id: "call_w", approved: true });
    expect(resolveBody.messages).toEqual(wireMessages);
    expect(screen.queryByTestId("chat-pending")).not.toBeInTheDocument();
  });

  it("declines a pending write without executing it", async () => {
    chatMock.mockResolvedValueOnce({
      messages: [],
      reply: null,
      events: [],
      pending: { id: "call_w", tool: "archive_spool", arguments: { spool_id: 3 } },
      stopped_reason: null,
    });
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.type(screen.getByTestId("chat-input"), "Archive it");
    await user.click(screen.getByTestId("chat-send"));
    await screen.findByTestId("chat-pending");

    chatMock.mockResolvedValueOnce(textResponse("Left untouched."));
    await user.click(screen.getByTestId("chat-decline"));

    expect(await screen.findByText("chat.action_declined")).toBeInTheDocument();
    expect(chatMock.mock.calls[1][0].resolve).toEqual({ id: "call_w", approved: false });
  });

  it("rolls back the optimistic user entry and restores the draft on failure", async () => {
    chatMock.mockRejectedValue(new Error("The AI endpoint is unreachable: ConnectError."));
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.type(screen.getByTestId("chat-input"), "hello");
    await user.click(screen.getByTestId("chat-send"));

    expect(await screen.findByText("The AI endpoint is unreachable: ConnectError.")).toBeInTheDocument();
    expect(screen.getByTestId("chat-input")).toHaveValue("hello");
    expect(screen.getByText("chat.empty")).toBeInTheDocument();
  });

  it("shows the step-budget notice when the loop was cut short", async () => {
    chatMock.mockResolvedValue(textResponse("", { reply: null, stopped_reason: "step_budget" }));
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.type(screen.getByTestId("chat-input"), "loop forever");
    await user.click(screen.getByTestId("chat-send"));

    expect(await screen.findByText("chat.step_budget")).toBeInTheDocument();
  });
});

describe("ChatPanel voice input (#363)", () => {
  it("hides the mic unless the feature is on, STT is configured, and the browser can record", () => {
    stubRecordingSupport();
    voiceFeature = "true";
    sttConfigured = false; // feature on, but no STT endpoint -> no mic
    render(<ChatPanel />);
    expect(screen.queryByTestId("chat-mic")).not.toBeInTheDocument();
  });

  it("records on hold, transcribes on release, and lands the transcript editable in the box", async () => {
    stubRecordingSupport();
    voiceFeature = "true";
    sttConfigured = true;
    transcribeMock.mockResolvedValue({ text: "log twenty grams on the orange prusament" });
    render(<ChatPanel />);

    const mic = screen.getByTestId("chat-mic");
    fireEvent.pointerDown(mic);
    expect(await screen.findByTestId("voice-recording")).toBeInTheDocument();

    fireEvent.pointerUp(mic);
    await waitFor(() => expect(transcribeMock).toHaveBeenCalledTimes(1));
    const body = transcribeMock.mock.calls[0][0];
    expect(body.mime).toBe("audio/webm");
    expect(body.language).toBe("en");
    expect(typeof body.audio_base64).toBe("string");

    // Transcribe-then-review: the text is in the input, nothing was sent.
    await waitFor(() =>
      expect(screen.getByTestId("chat-input")).toHaveValue("log twenty grams on the orange prusament"),
    );
    expect(chatMock).not.toHaveBeenCalled();
  });

  it("sends immediately when auto-send is opted in", async () => {
    stubRecordingSupport();
    voiceFeature = "true";
    voiceAutoSend = "true";
    sttConfigured = true;
    transcribeMock.mockResolvedValue({ text: "how much PLA is left" });
    chatMock.mockResolvedValue(textResponse("Plenty."));
    render(<ChatPanel />);

    const mic = screen.getByTestId("chat-mic");
    fireEvent.pointerDown(mic);
    await screen.findByTestId("voice-recording");
    fireEvent.pointerUp(mic);

    await waitFor(() => expect(chatMock).toHaveBeenCalledTimes(1));
    expect(chatMock.mock.calls[0][0].messages).toEqual([{ role: "user", content: "how much PLA is left" }]);
    expect(await screen.findByText("Plenty.")).toBeInTheDocument();
  });

  it("cancels without transcribing when the pointer slides away", async () => {
    stubRecordingSupport();
    voiceFeature = "true";
    sttConfigured = true;
    render(<ChatPanel />);

    const mic = screen.getByTestId("chat-mic");
    fireEvent.pointerDown(mic);
    await screen.findByTestId("voice-recording");
    fireEvent.pointerLeave(mic);

    await waitFor(() => expect(screen.queryByTestId("voice-recording")).not.toBeInTheDocument());
    expect(transcribeMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("chat-input")).toHaveValue("");
  });

  it("speaks replies through the browser when the toggle is on", async () => {
    stubRecordingSupport();
    voiceFeature = "true";
    sttConfigured = true;
    const speak = vi.fn();
    vi.stubGlobal("speechSynthesis", { speak, cancel: vi.fn() });
    class FakeUtterance {
      lang = "";
      constructor(public text: string) {}
    }
    vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
    chatMock.mockResolvedValue(textResponse("One spool left."));
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.click(screen.getByTestId("chat-speak"));
    await user.type(screen.getByTestId("chat-input"), "how much?");
    await user.click(screen.getByTestId("chat-send"));

    await waitFor(() => expect(speak).toHaveBeenCalledTimes(1));
    expect(speak.mock.calls[0][0].text).toBe("One spool left.");
    expect(speak.mock.calls[0][0].lang).toBe("en");
  });
});
