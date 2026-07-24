import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The managed-pull section (#364, F2) is exercised hermetically: the installed-model query
// and the streaming pull are mocked. What we pin is that installed models are marked and the
// rest offer a pull that streams by model name.

const modelsMock = vi.fn<() => { is_ollama: boolean; installed: string[] } | undefined>();
const pullMock = vi.fn();

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, opts?: { model?: string }) => (opts?.model ? `${key}:${opts.model}` : key),
}));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock("../../utils/queryAI", () => ({
  useOllamaModels: () => ({ data: modelsMock() }),
  pullOllamaModel: (model: string, onEvent: unknown) => pullMock(model, onEvent),
}));

import { OllamaModelsSection } from "./ollamaModels";

beforeEach(() => {
  vi.clearAllMocks();
  modelsMock.mockReturnValue({ is_ollama: true, installed: ["qwen3:8b"] });
  pullMock.mockResolvedValue(undefined);
});

describe("OllamaModelsSection (#364)", () => {
  it("marks installed models and offers a pull (with size) for the rest", () => {
    render(<OllamaModelsSection />);
    // qwen3:8b is installed -> shows the installed tag; llama3.2:3b is not -> a pull button.
    expect(screen.getAllByText("settings.ai.models.installed").length).toBeGreaterThan(0);
    expect(screen.getByTestId("pull-llama3.2:3b")).toBeInTheDocument();
    expect(screen.getByTestId("pull-llama3.2:3b").textContent).toContain("GB");
    expect(screen.queryByTestId("pull-qwen3:8b")).not.toBeInTheDocument();
  });

  it("streams a pull for the clicked model", async () => {
    const user = userEvent.setup();
    render(<OllamaModelsSection />);
    await user.click(screen.getByTestId("pull-llama3.2:3b"));
    expect(pullMock).toHaveBeenCalledWith("llama3.2:3b", expect.any(Function));
  });
});
