import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AIStatus } from "../../utils/queryAI";

// The panel is exercised hermetically: every server interaction is behind the two
// query modules, mocked here. What we pin down is the #359 contract visible to the
// user — invisible-unless-enabled gating with inline reasons, the write-only key
// affordance, env-locking, and honest tri-state capability reporting.

const statusMock = vi.fn<() => AIStatus | undefined>();
const settingsMock = vi.fn<() => Record<string, { value: string }> | undefined>();
const probeMutate = vi.fn();
const setKeyMutate = vi.fn();
const setSettingMutate = vi.fn();
const decisionTestMutate = vi.fn();
const setDecisionKeyMutate = vi.fn();

vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string) => key }));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock("../../utils/queryAI", () => ({
  useAIStatus: () => ({ data: statusMock() }),
  useAIProbe: () => ({ mutate: probeMutate, isPending: false, isError: false, error: null }),
  useSetAIKey: () => ({ mutate: setKeyMutate, mutateAsync: vi.fn(), isPending: false }),
  useSetSTTKey: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useSetDecisionKey: () => ({
    mutate: setDecisionKeyMutate,
    mutateAsync: async (value: unknown) => setDecisionKeyMutate(value),
    isPending: false,
  }),
  useDecisionTest: () => ({ mutate: decisionTestMutate, isPending: false, isError: false, error: null }),
  // The managed-pull section renders when the probe reports an Ollama endpoint; it has its
  // own dedicated test file, so here we only stub the two exports it reaches for.
  useOllamaModels: () => ({ data: { is_ollama: true, installed: [] } }),
  pullOllamaModel: vi.fn(),
}));
vi.mock("../../utils/querySettings", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../utils/querySettings")>()),
  useGetSettings: () => ({ data: settingsMock() }),
  useSetSetting: (key: string) => ({
    mutate: (value: unknown) => setSettingMutate(key, value),
    mutateAsync: async (value: unknown) => setSettingMutate(key, value),
    isPending: false,
  }),
}));

import { AISettings } from "./aiSettings";

const baseStatus: AIStatus = {
  configured: false,
  base_url: null,
  model: null,
  vision_model: null,
  api_key_set: false,
  stt_configured: false,
  stt_base_url: null,
  stt_model: null,
  stt_api_key_set: false,
  decision_configured: false,
  decision_base_url: null,
  decision_model: null,
  decision_api_key_set: false,
  env_locked: [],
  features: { chat: false, scan_to_spool: false, nl_search: false, mcp: false, voice: false },
  capabilities: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  statusMock.mockReturnValue(baseStatus);
  settingsMock.mockReturnValue({});
});

describe("AISettings (#359)", () => {
  it("keeps every feature toggle disabled with a reason while unconfigured", () => {
    render(<AISettings />);
    for (const feature of ["chat", "scan_to_spool", "nl_search", "voice"]) {
      expect(screen.getByTestId(`toggle-${feature}`)).toBeDisabled();
    }
    // Three features wait on the chat endpoint; voice waits on a speech-to-text endpoint.
    expect(screen.getAllByText("settings.ai.features.requires_config")).toHaveLength(3);
    expect(screen.getByText("settings.ai.features.requires_stt")).toBeInTheDocument();
  });

  it("lets features be enabled once configured, persisting the matching setting", async () => {
    statusMock.mockReturnValue({ ...baseStatus, configured: true, base_url: "http://o:11434/v1", model: "m" });
    const user = userEvent.setup();
    render(<AISettings />);

    const chatInput = screen.getByTestId("toggle-chat") as HTMLInputElement;
    expect(chatInput).toBeEnabled();
    await user.click(chatInput);
    expect(setSettingMutate).toHaveBeenCalledWith("ai_feature_chat", true);
  });

  it("blocks enabling Scan-to-Spool with an inline reason when the probe reports no vision", () => {
    statusMock.mockReturnValue({
      ...baseStatus,
      configured: true,
      base_url: "http://o:11434/v1",
      model: "m",
      capabilities: {
        ok: true,
        error: null,
        latency_ms: 12,
        models: ["m"],
        chat: "yes",
        tools: "yes",
        vision: "no",
        is_ollama: true,
        checked_at: null,
      },
    });
    render(<AISettings />);

    expect(screen.getByTestId("toggle-scan_to_spool")).toBeDisabled();
    expect(screen.getByText("settings.ai.features.requires_vision")).toBeInTheDocument();
    // The other configurable features stay enabled.
    expect(screen.getByTestId("toggle-chat")).toBeEnabled();
  });

  it("renders the cached probe with honest tri-state wording", () => {
    statusMock.mockReturnValue({
      ...baseStatus,
      configured: true,
      capabilities: {
        ok: true,
        error: null,
        latency_ms: 142,
        models: ["a", "b"],
        chat: "yes",
        tools: "unknown",
        vision: "unknown",
        is_ollama: false,
        checked_at: null,
      },
    });
    render(<AISettings />);

    expect(screen.getByText("settings.ai.probe.reachable")).toBeInTheDocument();
    expect(screen.getAllByText(/settings\.ai\.probe\.unknown/)).toHaveLength(2);
  });

  it("never shows a stored key, offers replace-and-clear instead", async () => {
    statusMock.mockReturnValue({ ...baseStatus, api_key_set: true });
    const user = userEvent.setup();
    render(<AISettings />);

    const keyInput = screen.getByPlaceholderText("settings.ai.api_key.placeholder_set") as HTMLInputElement;
    expect(keyInput.value).toBe("");

    await user.click(screen.getByRole("button", { name: "settings.ai.api_key.clear" }));
    expect(setKeyMutate).toHaveBeenCalledWith(null);
  });

  it("disables env-locked fields and says why", () => {
    statusMock.mockReturnValue({
      ...baseStatus,
      base_url: "http://env:11434/v1",
      env_locked: ["base_url"],
    });
    render(<AISettings />);

    expect(screen.getByPlaceholderText("http://localhost:11434/v1")).toBeDisabled();
    expect(screen.getByText("settings.ai.env_locked")).toBeInTheDocument();
  });

  it("sends unsaved form values with the connection test, omitting an untyped key", async () => {
    statusMock.mockReturnValue({ ...baseStatus, base_url: "http://o:11434/v1", model: "m" });
    const user = userEvent.setup();
    render(<AISettings />);

    await user.click(screen.getByRole("button", { name: "settings.ai.test" }));
    expect(probeMutate).toHaveBeenCalledTimes(1);
    const [overrides] = probeMutate.mock.calls[0];
    expect(overrides).toMatchObject({ base_url: "http://o:11434/v1", model: "m" });
    expect(overrides).not.toHaveProperty("api_key");
  });

  it("lets the MCP server be enabled even while no provider is configured (#360)", () => {
    // MCP needs no LLM endpoint — its toggle must stay enabled when the others are blocked.
    render(<AISettings />);
    expect(screen.getByTestId("toggle-mcp")).toBeEnabled();
    expect(screen.getByTestId("toggle-chat")).toBeDisabled();
  });

  it("renders the speech-to-text endpoint fields (#363)", () => {
    render(<AISettings />);
    expect(screen.getByText("settings.ai.stt.title")).toBeInTheDocument();
    expect(screen.getByText("settings.ai.stt.base_url.label")).toBeInTheDocument();
  });

  it("blocks Voice until a speech-to-text endpoint is configured, then allows it (#363)", () => {
    const { rerender } = render(<AISettings />);
    expect(screen.getByTestId("toggle-voice")).toBeDisabled();
    expect(screen.getByText("settings.ai.features.requires_stt")).toBeInTheDocument();

    statusMock.mockReturnValue({ ...baseStatus, stt_configured: true });
    rerender(<AISettings />);
    expect(screen.getByTestId("toggle-voice")).toBeEnabled();
  });

  it("renders the decision model section", () => {
    render(<AISettings />);
    expect(screen.getByText("settings.ai.decision.title")).toBeInTheDocument();
    expect(screen.getByText("settings.ai.decision.base_url.label")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("https://api.typesafe.ai")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("jev-latest")).toBeInTheDocument();
  });

  it("saves the decision model base URL, model and key on submit", async () => {
    const user = userEvent.setup();
    render(<AISettings />);

    await user.type(screen.getByPlaceholderText("https://api.typesafe.ai"), "https://api.typesafe.ai");
    await user.type(screen.getByPlaceholderText("jev-latest"), "jev-latest");
    const keyInputs = screen.getAllByPlaceholderText("settings.ai.api_key.placeholder_unset");
    await user.type(keyInputs[keyInputs.length - 1], "secret");
    await user.click(screen.getByRole("button", { name: "buttons.save" }));

    expect(setSettingMutate).toHaveBeenCalledWith("ai_decision_base_url", "https://api.typesafe.ai");
    expect(setSettingMutate).toHaveBeenCalledWith("ai_decision_model", "jev-latest");
    expect(setDecisionKeyMutate).toHaveBeenCalledWith("secret");
  });

  it("offers Clear for a stored decision key that is no longer used", async () => {
    // Saved for another base URL: not in use, but still stored, so it must be clearable.
    statusMock.mockReturnValue({ ...baseStatus, decision_api_key_set: false, decision_api_key_stored: true });
    const user = userEvent.setup();
    render(<AISettings />);

    const clearButtons = screen.getAllByRole("button", { name: "settings.ai.api_key.clear" });
    await user.click(clearButtons[clearButtons.length - 1]);
    expect(setDecisionKeyMutate).toHaveBeenCalledWith(null);
  });

  it("disables env-locked decision fields and says why", () => {
    statusMock.mockReturnValue({
      ...baseStatus,
      decision_base_url: "https://env.example.com",
      env_locked: ["decision_base_url", "decision_model"],
    });
    render(<AISettings />);

    expect(screen.getByPlaceholderText("https://api.typesafe.ai")).toBeDisabled();
    expect(screen.getByPlaceholderText("jev-latest")).toBeDisabled();
    expect(screen.getAllByText("settings.ai.env_locked")).toHaveLength(2);
  });

  it("sends unsaved form values with the decision model test", async () => {
    statusMock.mockReturnValue({
      ...baseStatus,
      decision_base_url: "https://api.typesafe.ai",
      decision_model: "jev-latest",
    });
    const user = userEvent.setup();
    render(<AISettings />);

    const baseUrlInput = screen.getByPlaceholderText("https://api.typesafe.ai");
    await user.clear(baseUrlInput);
    await user.type(baseUrlInput, "https://openrouter.ai/api");
    // An emptied model box means "use the default", so it is sent as "" rather than left out.
    await user.clear(screen.getByPlaceholderText("jev-latest"));
    const keyInputs = screen.getAllByPlaceholderText("settings.ai.api_key.placeholder_unset");
    await user.type(keyInputs[keyInputs.length - 1], "sk-typed");
    await user.click(screen.getByRole("button", { name: "settings.ai.decision.test" }));

    expect(decisionTestMutate).toHaveBeenCalledTimes(1);
    const [overrides, options] = decisionTestMutate.mock.calls[0];
    expect(overrides).toEqual({ base_url: "https://openrouter.ai/api", model: "", api_key: "sk-typed" });

    act(() => options.onSuccess({ ok: true, error: null, latency_ms: 42, model: "jev-latest" }));
    expect(screen.getByTestId("decision-test-result").textContent).toContain("settings.ai.decision.test_success");
  });

  it("leaves the key out of the decision model test when none is typed", async () => {
    statusMock.mockReturnValue({ ...baseStatus, decision_base_url: "https://api.typesafe.ai" });
    const user = userEvent.setup();
    render(<AISettings />);

    await user.click(screen.getByRole("button", { name: "settings.ai.decision.test" }));
    const [overrides] = decisionTestMutate.mock.calls[0];
    expect(overrides).toMatchObject({ base_url: "https://api.typesafe.ai" });
    expect(overrides).not.toHaveProperty("api_key");
  });

  it("shows a copyable MCP config block only once MCP is enabled", () => {
    const { rerender } = render(<AISettings />);
    expect(screen.queryByTestId("mcp-config")).not.toBeInTheDocument();

    settingsMock.mockReturnValue({ ai_feature_mcp: { value: "true" } });
    rerender(<AISettings />);
    const block = screen.getByTestId("mcp-config");
    expect(block.textContent).toContain("mcpServers");
    expect(block.textContent).toContain("/mcp");
  });
});
