import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSimilarVendor } from "./querySimilar";

// Behavioral tests for useSimilarVendor: the debounced client for POST /vendor/similar.
// Oracle: the documented contract - debounce 500ms, skip short names, cancel a superseded
// request, and stay silent (nulls, no throw) on any failure including a read-only 403.

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useSimilarVendor", () => {
  it("does not call the server for a name shorter than two characters", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useSimilarVendor("e"));
    await vi.advanceTimersByTimeAsync(1000);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("waits 500ms after the last change before calling the server", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ exact: null, suggestion: null }),
    })) as unknown as typeof fetch;
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = renderHook(({ name }) => useSimilarVendor(name), { initialProps: { name: "es" } });
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(fetchMock).not.toHaveBeenCalled();

    rerender({ name: "esu" });
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(fetchMock).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain("/vendor/similar");
    expect(JSON.parse(init.body as string)).toEqual({ name: "esu" });
  });

  it("returns the exact and suggestion matches from a successful response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          exact: { id: 1, name: "eSUN", probability: null },
          suggestion: null,
        }),
      })) as unknown as typeof fetch,
    );

    const { result } = renderHook(() => useSimilarVendor("esun"));
    await act(() => vi.advanceTimersByTimeAsync(500));

    expect(result.current).toEqual({ exact: { id: 1, name: "eSUN", probability: null }, suggestion: null });
  });

  it("cancels a stale request when the name changes before the debounce fires", async () => {
    const inits: (RequestInit | undefined)[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      inits.push(init);
      return { ok: true, json: async () => ({ exact: null, suggestion: null }) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = renderHook(({ name }) => useSimilarVendor(name), { initialProps: { name: "esu" } });
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    rerender({ name: "esun" });
    await act(() => vi.advanceTimersByTimeAsync(500));

    // The first request's controller was aborted before the second one ever fired.
    expect((inits[0]?.signal as AbortSignal).aborted).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("stays silent (nulls, no throw) on a 403 from a read-only user", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 403 }) as Response),
    );

    const { result } = renderHook(() => useSimilarVendor("esun"));
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(result.current).toEqual({ exact: null, suggestion: null });
  });

  it("stays silent (nulls, no throw) on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );

    const { result } = renderHook(() => useSimilarVendor("esun"));
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(result.current).toEqual({ exact: null, suggestion: null });
  });
});
