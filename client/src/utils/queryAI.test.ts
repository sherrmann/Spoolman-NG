import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PullProgress } from "./queryAI";

// The NDJSON stream parser behind the managed model pull (#364), tested against a
// hand-rolled reader: chunk boundaries fall mid-line on real networks, and an
// {"error": ...} line relayed by the server must reject, not report progress.

const apiFetchMock = vi.fn();

vi.mock("./authReloadHandler", () => ({ apiFetch: (...args: unknown[]) => apiFetchMock(...args) }));
vi.mock("./url", () => ({ getAPIURL: () => "/api/v1" }));

import { pullOllamaModel } from "./queryAI";

function streamedResponse(chunks: string[]): { ok: boolean; body: { getReader: () => unknown } } {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    ok: true,
    body: {
      getReader: () => ({
        read: () =>
          Promise.resolve(
            index < chunks.length ? { done: false, value: encoder.encode(chunks[index++]) } : { done: true },
          ),
      }),
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("pullOllamaModel (#364)", () => {
  it("parses NDJSON progress across arbitrary chunk boundaries", async () => {
    apiFetchMock.mockResolvedValue(
      streamedResponse([
        '{"status": "pulling manifest"}\n{"status": "pulling',
        ' abc", "total": 100, "completed": 40}\n',
        '{"status": "success"}\n',
      ]),
    );

    const events: PullProgress[] = [];
    await pullOllamaModel("qwen3:8b", (event) => events.push(event));

    expect(events.map((event) => event.status)).toEqual(["pulling manifest", "pulling abc", "success"]);
    expect(events[1].completed).toBe(40);
    const [, init] = apiFetchMock.mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ model: "qwen3:8b" });
  });

  it("rejects when the server relays an Ollama error line", async () => {
    apiFetchMock.mockResolvedValue(streamedResponse(['{"error": "Ollama returned HTTP 500. boom"}\n']));
    await expect(pullOllamaModel("qwen3:8b", vi.fn())).rejects.toThrow("Ollama returned HTTP 500. boom");
  });

  it("rejects on a non-OK response with the detail message", async () => {
    apiFetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: () => Promise.resolve({ detail: "The configured endpoint is not an Ollama server." }),
    });
    await expect(pullOllamaModel("qwen3:8b", vi.fn())).rejects.toThrow(
      "The configured endpoint is not an Ollama server.",
    );
  });
});
