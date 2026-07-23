import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AIChatResponse } from "../utils/queryAI";

// The chat flow is tested hermetically: the chat mutation, settings, locale and
// location are mocked; what is asserted is the contract of the UI - transcript
// round-tripping, confirm-gated writes, and invisibility while disabled.

const chatMock = vi.fn();
let chatFeature = "true";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useGetLocale: () => () => "en",
}));
vi.mock("react-router", () => ({ useLocation: () => ({ pathname: "/spool" }) }));
vi.mock("../utils/queryAI", () => ({
  useAIChat: () => ({ mutateAsync: chatMock, isPending: false }),
}));
vi.mock("../utils/querySettings", () => ({
  useGetSettings: () => ({ data: { ai_feature_chat: { value: chatFeature } } }),
}));

import ChatDrawer, { ChatPanel } from "./chatDrawer";

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
  chatFeature = "true";
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
