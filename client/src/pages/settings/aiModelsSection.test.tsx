import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AIProbeResult, PullProgress } from "../../utils/queryAI";

const pullMock = vi.fn();

vi.mock("@refinedev/core", () => ({ useTranslate: () => (key: string) => key }));
vi.mock("../../utils/queryAI", () => ({
  pullOllamaModel: (model: string, onProgress: (p: PullProgress) => void) => pullMock(model, onProgress),
}));

import { OllamaModelsSection } from "./aiModelsSection";

const capabilities: AIProbeResult = {
  ok: true,
  error: null,
  latency_ms: 10,
  models: ["qwen3:8b"],
  chat: "yes",
  tools: "yes",
  vision: "unknown",
  is_ollama: true,
  checked_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("OllamaModelsSection (#364)", () => {
  it("marks installed models and offers Pull with the size for the rest", () => {
    render(<OllamaModelsSection capabilities={capabilities} onPulled={vi.fn()} />);
    expect(screen.getByTestId("model-installed-qwen3:8b")).toBeInTheDocument();
    expect(screen.queryByTestId("model-pull-qwen3:8b")).not.toBeInTheDocument();
    expect(screen.getByTestId("model-pull-qwen2.5vl:7b")).toBeInTheDocument();
    // Sizes are shown before pulling (i18n key carries the interpolation).
    expect(screen.getAllByText(/settings\.ai\.models\.size/).length).toBeGreaterThan(0);
  });

  it("shows progress during a pull and refreshes the probe when it completes", async () => {
    let progressCallback: ((p: PullProgress) => void) | undefined;
    let finish: (() => void) | undefined;
    pullMock.mockImplementation((_model: string, onProgress: (p: PullProgress) => void) => {
      progressCallback = onProgress;
      return new Promise<void>((resolve) => {
        finish = resolve;
      });
    });
    const onPulled = vi.fn();
    const user = userEvent.setup();
    render(<OllamaModelsSection capabilities={capabilities} onPulled={onPulled} />);

    await user.click(screen.getByTestId("model-pull-qwen2.5vl:7b"));
    expect(pullMock).toHaveBeenCalledWith("qwen2.5vl:7b", expect.any(Function));

    progressCallback?.({ status: "pulling", total: 1000, completed: 250 });
    await waitFor(() => expect(screen.getByTestId("model-progress-qwen2.5vl:7b")).toBeInTheDocument());

    finish?.();
    await waitFor(() => expect(screen.getByTestId("model-installed-qwen2.5vl:7b")).toBeInTheDocument());
    expect(onPulled).toHaveBeenCalledTimes(1);
  });

  it("surfaces pull failures inline and keeps the probe state untouched", async () => {
    pullMock.mockRejectedValue(new Error("Ollama returned HTTP 500. no space left"));
    const onPulled = vi.fn();
    const user = userEvent.setup();
    render(<OllamaModelsSection capabilities={capabilities} onPulled={onPulled} />);

    await user.click(screen.getByTestId("model-pull-qwen3:4b"));

    expect(await screen.findByText("Ollama returned HTTP 500. no space left")).toBeInTheDocument();
    expect(onPulled).not.toHaveBeenCalled();
  });
});
