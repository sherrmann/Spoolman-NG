import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatEvent, ChatTurnRequest } from "../utils/queryAI";

// The drawer is exercised hermetically: the SSE stream is behind streamChat, mocked here so
// we can script the agent's events. What we pin is the #362 contract — invisible unless the
// toggle is on, a mutation surfaces as a confirm-card, and Cancel re-posts with
// decision="cancel" (so nothing is executed).

const settingsMock = vi.fn<() => Record<string, { value: string }> | undefined>();
const streamChat = vi.fn<(body: ChatTurnRequest, onEvent: (e: ChatEvent) => void) => Promise<void>>();

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useGetLocale: () => () => "en",
}));
vi.mock("react-router", () => ({ useLocation: () => ({ pathname: "/spool" }) }));
vi.mock("../utils/querySettings", () => ({ useGetSettings: () => ({ data: settingsMock() }) }));
vi.mock("../utils/queryAI", () => ({
  streamChat: (body: ChatTurnRequest, onEvent: (e: ChatEvent) => void) => streamChat(body, onEvent),
  useChatAction: () => ({ mutateAsync: vi.fn(), isPending: false }),
  spoolListFilterLink: () => "/spool#filters=%5B%5D",
}));

import { ChatDrawer } from "./chatDrawer";

beforeEach(() => {
  vi.clearAllMocks();
  settingsMock.mockReturnValue({ ai_feature_chat: { value: "true" } });
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
