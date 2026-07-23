import { render, screen } from "@testing-library/react";
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

vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string) => key }));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock("../../utils/queryAI", () => ({
  useAIStatus: () => ({ data: statusMock() }),
  useAIProbe: () => ({ mutate: probeMutate, isPending: false, isError: false, error: null }),
  useSetAIKey: () => ({ mutate: setKeyMutate, mutateAsync: vi.fn(), isPending: false }),
}));
const authStatusMock = vi.fn();
vi.mock("../../utils/auth", () => ({ useAuthStatus: () => ({ data: authStatusMock() }) }));
vi.mock("../../utils/url", () => ({ getBasePath: () => "" }));
vi.mock("../../utils/querySettings", () => ({
  useGetSettings: () => ({ data: settingsMock() }),
  useSetSetting: (key: string) => ({
    mutate: (value: unknown) => setSettingMutate(key, value),
    mutateAsync: vi.fn(),
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
  stt_base_url: null,
  stt_model: null,
  stt_api_key_set: false,
  stt_configured: false,
  env_locked: [],
  features: { chat: false, scan_to_spool: false, nl_search: false, voice: false },
  capabilities: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  statusMock.mockReturnValue(baseStatus);
  settingsMock.mockReturnValue({});
  authStatusMock.mockReturnValue({ auth_required: false });
});

describe("AISettings (#359)", () => {
  it("keeps every feature toggle disabled with a reason while unconfigured", () => {
    render(<AISettings />);
    for (const feature of ["chat", "scan_to_spool", "nl_search", "voice"]) {
      expect(screen.getByTestId(`toggle-${feature}`)).toBeDisabled();
    }
    expect(screen.getAllByText("settings.ai.features.requires_config")).toHaveLength(4);
  });

  it("blocks Voice with an inline reason until an STT model is configured (#363)", () => {
    statusMock.mockReturnValue({ ...baseStatus, configured: true, base_url: "http://o:11434/v1", model: "m" });
    render(<AISettings />);
    expect(screen.getByTestId("toggle-voice")).toBeDisabled();
    expect(screen.getByText("settings.ai.features.requires_stt")).toBeInTheDocument();
  });

  it("lets Voice be enabled once STT is configured and offers the auto-send opt-in", async () => {
    statusMock.mockReturnValue({
      ...baseStatus,
      configured: true,
      base_url: "http://o:11434/v1",
      model: "m",
      stt_model: "whisper-1",
      stt_configured: true,
    });
    settingsMock.mockReturnValue({ ai_feature_voice: { value: "true" } });
    const user = userEvent.setup();
    render(<AISettings />);

    expect(screen.getByTestId("toggle-voice")).toBeEnabled();
    // Auto-send is the explicit opt-in sub-toggle, off by default.
    const autoSend = screen.getByTestId("toggle-voice-auto-send") as HTMLInputElement;
    expect(autoSend).not.toBeChecked();
    await user.click(autoSend);
    expect(setSettingMutate).toHaveBeenCalledWith("ai_voice_auto_send", true);
  });

  it("keeps the STT key write-only with its own clear affordance", async () => {
    statusMock.mockReturnValue({ ...baseStatus, stt_api_key_set: true });
    const user = userEvent.setup();
    render(<AISettings />);

    await user.click(screen.getByTestId("stt-key-clear"));
    expect(setKeyMutate).toHaveBeenCalledWith({ stt_api_key: null });
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
    expect(setKeyMutate).toHaveBeenCalledWith({ api_key: null });
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

  it("persists the MCP toggle and hides connection details while off", async () => {
    settingsMock.mockReturnValue({ mcp_enabled: { value: "false" } });
    const user = userEvent.setup();
    render(<AISettings />);

    expect(screen.queryByTestId("mcp-url")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("toggle-mcp"));
    expect(setSettingMutate).toHaveBeenCalledWith("mcp_enabled", true);
  });

  it("shows the connector URL and copies a client config when MCP is on", async () => {
    settingsMock.mockReturnValue({ mcp_enabled: { value: "true" } });
    authStatusMock.mockReturnValue({ auth_required: true });
    const user = userEvent.setup();
    // Define the clipboard mock AFTER userEvent.setup(), which installs its own stub.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<AISettings />);

    const url = (screen.getByTestId("mcp-url") as HTMLInputElement).value;
    expect(url).toMatch(/\/mcp$/);
    // Auth is enabled, so the copied config carries the bearer placeholder and the note shows.
    expect(screen.getByText("settings.ai.mcp.auth_note")).toBeInTheDocument();

    await user.click(screen.getByTestId("mcp-copy"));
    const copied = JSON.parse(writeText.mock.calls[0][0]);
    expect(copied.mcpServers.spoolman.url).toBe(url);
    expect(copied.mcpServers.spoolman.headers.Authorization).toContain("YOUR_SPOOLMAN_TOKEN");
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
});
