import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSimilarVendor } from "./querySimilar";

// Behavioral tests for useSimilarVendor: the debounced client for POST /vendor/similar.
// Oracle: the documented contract - debounce 500ms, skip short names, clear a stale result the
// instant the name changes (rather than only once a fresh answer arrives), never let a
// slow/out-of-order response for an old name win, and stay silent (nulls, no throw) on any
// failure including a read-only 403.

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** A fetch response whose settlement the test controls, so ordering can be chosen deliberately. */
function deferredResponse() {
  let resolveFn!: (value: Response) => void;
  let rejectFn!: (reason?: unknown) => void;
  const promise = new Promise<Response>((resolve, reject) => {
    resolveFn = resolve;
    rejectFn = reject;
  });
  return {
    promise,
    resolve: (data: unknown) => resolveFn({ ok: true, json: async () => data } as Response),
    reject: (reason?: unknown) => rejectFn(reason),
  };
}

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

  it("clears the result immediately once the name changes, before the next debounce can fire", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ exact: { id: 1, name: "eSUN", probability: null }, suggestion: null }),
      })) as unknown as typeof fetch,
    );

    const { rerender, result } = renderHook(({ name }) => useSimilarVendor(name), {
      initialProps: { name: "esun" },
    });
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(result.current.exact).not.toBeNull();

    // No time has passed - nowhere near enough for a new debounce/fetch cycle - but the hint for
    // the old name must already be gone rather than lingering until the new answer comes back.
    rerender({ name: "esun pro" });
    expect(result.current).toEqual({ exact: null, suggestion: null });
  });

  it("cancels a stale request, and a late out-of-order response for the old name never wins", async () => {
    const responses = [deferredResponse(), deferredResponse()];
    let callIndex = 0;
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      const current = responses[callIndex++];
      // Mirrors real fetch()/AbortController behavior: an aborted request's promise rejects.
      init?.signal?.addEventListener("abort", () => current.reject(new DOMException("Aborted", "AbortError")));
      return current.promise;
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender, result } = renderHook(({ name }) => useSimilarVendor(name), { initialProps: { name: "esu" } });
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    rerender({ name: "esun" });
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // Resolve the newer ("esun") request first, then the stale ("esu") one arrives late - out of
    // order. (The stale one was already rejected by its own abort listener when it was cancelled
    // above, so resolving it here is a no-op - exactly what a real aborted fetch() promise does.)
    await act(async () => {
      responses[1].resolve({ exact: { id: 2, name: "eSUN", probability: null }, suggestion: null });
    });
    expect(result.current).toEqual({ exact: { id: 2, name: "eSUN", probability: null }, suggestion: null });

    await act(async () => {
      responses[0].resolve({ exact: { id: 9, name: "Old Match", probability: null }, suggestion: null });
    });
    // The stale response for "esu" never displaces the current, fresher result.
    expect(result.current).toEqual({ exact: { id: 2, name: "eSUN", probability: null }, suggestion: null });
  });

  it("clears a previous result once the next name gets a 403 from a read-only user", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ exact: { id: 1, name: "eSUN", probability: null }, suggestion: null }),
    } as Response);
    fetchMock.mockResolvedValueOnce({ ok: false, status: 403 } as Response);
    vi.stubGlobal("fetch", fetchMock);

    const { rerender, result } = renderHook(({ name }) => useSimilarVendor(name), {
      initialProps: { name: "esun" },
    });
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(result.current.exact).not.toBeNull();

    rerender({ name: "bambu" });
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(result.current).toEqual({ exact: null, suggestion: null });
  });

  it("clears a previous result once the next name hits a network failure", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ exact: null, suggestion: { id: 5, name: "Bambu Lab", probability: 0.8 } }),
    } as Response);
    fetchMock.mockRejectedValueOnce(new Error("network down"));
    vi.stubGlobal("fetch", fetchMock);

    const { rerender, result } = renderHook(({ name }) => useSimilarVendor(name), {
      initialProps: { name: "bambu" },
    });
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(result.current.suggestion).not.toBeNull();

    rerender({ name: "esun" });
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(result.current).toEqual({ exact: null, suggestion: null });
  });
});
