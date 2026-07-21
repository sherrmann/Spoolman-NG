import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearApiToken, setApiToken, useApiTokenModal } from "./apiToken";
import { apiFetch, handleAuthResponseError, reloadIfAuthFailed, reloadOnAuthFailure } from "./authReloadHandler";

/** A minimal Response stub whose headers.get returns the given WWW-Authenticate value. */
function mockResponse(status: number, wwwAuthenticate: string | null = null): Response {
  return {
    status,
    headers: { get: (h: string) => (h.toLowerCase() === "www-authenticate" ? wwwAuthenticate : null) },
  } as unknown as Response;
}

// Regression cover for the 401 auto-reload behavior (TESTING_CANDIDATES row 58c):
// reload only for idempotent requests, a cooldown to bound reload loops, and SW
// unregistration first. Oracle: the observable effects (window.location.reload calls,
// SW unregister) with the clock and storage mocked at the boundary.

const originalLocation = window.location;
let reloadSpy: ReturnType<typeof vi.fn>;

function stubLocation() {
  reloadSpy = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, reload: reloadSpy },
  });
}

beforeEach(() => {
  // Clear the persisted cooldown flag ("spoolmanAuthReloadedAt") so reload
  // suppression can't leak between cases and make results order-dependent.
  localStorage.clear();
  vi.useFakeTimers();
  stubLocation();
});

afterEach(() => {
  vi.useRealTimers();
  Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  delete (navigator as { serviceWorker?: unknown }).serviceWorker;
});

describe("reloadOnAuthFailure", () => {
  it("reloads the page on the first failure", async () => {
    await reloadOnAuthFailure();
    expect(reloadSpy).toHaveBeenCalledOnce();
  });

  it("suppresses a second reload within the cooldown window", async () => {
    await reloadOnAuthFailure();
    await reloadOnAuthFailure();
    expect(reloadSpy).toHaveBeenCalledOnce();
  });

  it("reloads again once the cooldown has elapsed", async () => {
    await reloadOnAuthFailure();
    vi.advanceTimersByTime(30_001);
    await reloadOnAuthFailure();
    expect(reloadSpy).toHaveBeenCalledTimes(2);
  });

  it("unregisters service workers before reloading", async () => {
    const unregister = vi.fn().mockResolvedValue(true);
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: { getRegistrations: vi.fn().mockResolvedValue([{ unregister }]) },
    });
    await reloadOnAuthFailure();
    expect(unregister).toHaveBeenCalledTimes(1);
    expect(reloadSpy).toHaveBeenCalledOnce();
  });

  it("does NOT touch service workers under HA ingress (they can only be foreign)", async () => {
    // The ingress panel iframe is same-origin with the Home Assistant frontend, and
    // getRegistrations() is origin-wide — Spoolman never registers a SW under ingress
    // (#211), so unregistering here would destroy HA's own service worker.
    const unregister = vi.fn().mockResolvedValue(true);
    const getRegistrations = vi.fn().mockResolvedValue([{ unregister }]);
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: { getRegistrations },
    });
    window.SPOOLMAN_HA_INGRESS = true;
    await reloadOnAuthFailure();
    expect(getRegistrations).not.toHaveBeenCalled();
    expect(unregister).not.toHaveBeenCalled();
    expect(reloadSpy).toHaveBeenCalledOnce(); // the reload itself still happens
  });
});

describe("handleAuthResponseError", () => {
  it("reloads on a 401 for an idempotent GET, and re-rejects", async () => {
    await expect(
      handleAuthResponseError({ response: { status: 401 }, config: { method: "get" } }),
    ).rejects.toBeDefined();
    expect(reloadSpy).toHaveBeenCalledOnce();
  });

  it("does NOT reload on a 401 for a mutating request (preserves unsaved data)", async () => {
    await expect(
      handleAuthResponseError({ response: { status: 401 }, config: { method: "post" } }),
    ).rejects.toBeDefined();
    expect(reloadSpy).not.toHaveBeenCalled();
  });

  it("does NOT reload on a non-401 error", async () => {
    await expect(
      handleAuthResponseError({ response: { status: 500 }, config: { method: "get" } }),
    ).rejects.toBeDefined();
    expect(reloadSpy).not.toHaveBeenCalled();
  });

  it("defaults a missing method to GET and reloads", async () => {
    await expect(handleAuthResponseError({ response: { status: 401 } })).rejects.toBeDefined();
    expect(reloadSpy).toHaveBeenCalledOnce();
  });
});

// The bare-fetch reads (settings/fields/external/info/autocomplete) now route through
// apiFetch, extending the axios-only 401 recovery to the second transport. Issue #47.
describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    clearApiToken();
    useApiTokenModal.setState({ open: false });
  });

  it("reloads on a 401 GET (proxy) and returns the response unchanged", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(401)));
    const res = await apiFetch("/api/v1/setting/");
    expect(res.status).toBe(401);
    expect(reloadSpy).toHaveBeenCalledOnce();
  });

  it("does NOT reload on a 401 for a mutating request", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(401)));
    await apiFetch("/api/v1/setting/x", { method: "POST" });
    expect(reloadSpy).not.toHaveBeenCalled();
  });

  it("does NOT reload on a successful read", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(200)));
    await apiFetch("/api/v1/setting/");
    expect(reloadSpy).not.toHaveBeenCalled();
  });

  // Issue #48: a 401 from Spoolman's own token check opens the token modal instead of reloading.
  it("opens the token modal (not reload) on a 401 with WWW-Authenticate: Bearer", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(401, "Bearer")));
    await apiFetch("/api/v1/setting/");
    expect(useApiTokenModal.getState().open).toBe(true);
    expect(reloadSpy).not.toHaveBeenCalled();
  });

  it("attaches the stored API token as a bearer header", async () => {
    setApiToken("tok");
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(200));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/api/v1/setting/");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });
});

// The WebSocket provider probes /info on an abnormal drop; a real 401 reloads, a plain
// outage (network error) must not. Issue #47.
describe("reloadIfAuthFailed", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reloads when the probe comes back 401", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse(401)));
    await reloadIfAuthFailed("/api/v1/info");
    expect(reloadSpy).toHaveBeenCalledOnce();
  });

  it("does not reload or throw when the server is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    await expect(reloadIfAuthFailed("/api/v1/info")).resolves.toBeUndefined();
    expect(reloadSpy).not.toHaveBeenCalled();
  });
});
