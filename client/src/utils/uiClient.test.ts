import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UI_CLIENT_COOKIE_NAME, shouldShowUiClientSwitch, switchUiClient } from "./uiClient";
import type { IInfo } from "./useInfo";

// Cover for the per-browser client switcher: the cookie contract the backend reads
// (name/value/attributes), the deterministic service-worker teardown on a switch to svelte
// (with the HA-ingress guard from authReloadHandler.unregisterServiceWorkers still holding), and
// the two independent conditions that gate whether the control is shown at all. Oracle: the
// literal cookie string given in the contract, and the documented show/hide conditions — not the
// implementation.

const info = (overrides: Partial<IInfo>): IInfo => ({ version: "2026.7.14", ...overrides }) as IInfo;

/** A fully-eligible /info response: switching enabled, both bundles built. */
const switchableInfo = (overrides: Partial<IInfo> = {}): IInfo =>
  info({ client_switch_enabled: true, clients_available: ["react", "svelte"], client_active: "react", ...overrides });

const originalLocation = window.location;
let reloadSpy: ReturnType<typeof vi.fn>;

function stubLocation() {
  reloadSpy = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, reload: reloadSpy },
  });
}

/** Intercepts every write to document.cookie so the exact string handed to the setter (name,
 *  value and attributes) can be asserted on — document.cookie's getter never echoes attributes
 *  back, in jsdom or a real browser, so this is the only vantage point that can see them. */
function captureCookieWrites(): string[] {
  const writes: string[] = [];
  const descriptor = Object.getOwnPropertyDescriptor(Document.prototype, "cookie");
  if (!descriptor?.set || !descriptor.get) throw new Error("document.cookie has no accessor descriptor");
  const { get, set } = descriptor;
  Object.defineProperty(document, "cookie", {
    configurable: true,
    get,
    set(value: string) {
      writes.push(value);
      set.call(document, value);
    },
  });
  return writes;
}

beforeEach(() => {
  stubLocation();
});

afterEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  delete (navigator as { serviceWorker?: unknown }).serviceWorker;
  delete (window as Partial<Window>).SPOOLMAN_HA_INGRESS;
  document.cookie = `${UI_CLIENT_COOKIE_NAME}=; path=/; max-age=0`;
});

describe("switchUiClient", () => {
  it("writes the spoolman_ui cookie with the exact contract value and attributes for react", async () => {
    const writes = captureCookieWrites();
    await switchUiClient("react");
    expect(writes).toContain("spoolman_ui=react; path=/; max-age=31536000; SameSite=Lax");
  });

  it("writes the spoolman_ui cookie with the exact contract value and attributes for svelte", async () => {
    const writes = captureCookieWrites();
    await switchUiClient("svelte");
    expect(writes).toContain("spoolman_ui=svelte; path=/; max-age=31536000; SameSite=Lax");
  });

  it("reloads the page after switching to either client", async () => {
    await switchUiClient("react");
    expect(reloadSpy).toHaveBeenCalledOnce();
  });

  it("unregisters service workers before reloading when switching to svelte", async () => {
    const unregister = vi.fn().mockResolvedValue(true);
    const getRegistrations = vi.fn().mockResolvedValue([{ unregister }]);
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { getRegistrations } });

    await switchUiClient("svelte");

    expect(getRegistrations).toHaveBeenCalledOnce();
    expect(unregister).toHaveBeenCalledOnce();
    expect(reloadSpy).toHaveBeenCalledOnce();
  });

  it("does NOT unregister service workers when switching to react", async () => {
    const unregister = vi.fn().mockResolvedValue(true);
    const getRegistrations = vi.fn().mockResolvedValue([{ unregister }]);
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { getRegistrations } });

    await switchUiClient("react");

    expect(getRegistrations).not.toHaveBeenCalled();
    expect(unregister).not.toHaveBeenCalled();
    expect(reloadSpy).toHaveBeenCalledOnce();
  });

  it("does NOT touch service workers under HA ingress even when switching to svelte (#211)", async () => {
    // Same guard authReloadHandler.reloadOnAuthFailure relies on (via the shared
    // unregisterServiceWorkers helper): under ingress, getRegistrations() is origin-wide and
    // could only return Home Assistant's own registration, which unregistering would destroy.
    const unregister = vi.fn().mockResolvedValue(true);
    const getRegistrations = vi.fn().mockResolvedValue([{ unregister }]);
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: { getRegistrations } });
    window.SPOOLMAN_HA_INGRESS = true;

    await switchUiClient("svelte");

    expect(getRegistrations).not.toHaveBeenCalled();
    expect(unregister).not.toHaveBeenCalled();
    expect(reloadSpy).toHaveBeenCalledOnce(); // the switch (cookie + reload) still happens
  });
});

describe("shouldShowUiClientSwitch", () => {
  it("is false while /info is still loading (info undefined)", () => {
    expect(shouldShowUiClientSwitch(undefined)).toBe(false);
  });

  it("is false against an older backend that omits the fields entirely", () => {
    expect(shouldShowUiClientSwitch(info({}))).toBe(false);
  });

  it("is true when switching is enabled and both bundles are built", () => {
    expect(shouldShowUiClientSwitch(switchableInfo())).toBe(true);
  });

  it("is false when the operator disabled switching (client_switch_enabled: false)", () => {
    expect(shouldShowUiClientSwitch(switchableInfo({ client_switch_enabled: false }))).toBe(false);
  });

  it("is false when client_switch_enabled is absent (older/partial backend)", () => {
    const partial = switchableInfo();
    delete (partial as Partial<IInfo>).client_switch_enabled;
    expect(shouldShowUiClientSwitch(partial)).toBe(false);
  });

  it("is false when only react was built (source install, single bundle)", () => {
    expect(shouldShowUiClientSwitch(switchableInfo({ clients_available: ["react"] }))).toBe(false);
  });

  it("is false when only svelte was built (source install, single bundle)", () => {
    expect(shouldShowUiClientSwitch(switchableInfo({ clients_available: ["svelte"] }))).toBe(false);
  });

  it("is false when clients_available is empty", () => {
    expect(shouldShowUiClientSwitch(switchableInfo({ clients_available: [] }))).toBe(false);
  });

  it("is true when running as an installed standalone PWA (same origin/scope, a plain reload)", () => {
    const original = window.matchMedia;
    window.matchMedia = vi
      .fn()
      .mockImplementation((query: string) => ({ matches: query === "(display-mode: standalone)" }));
    try {
      expect(shouldShowUiClientSwitch(switchableInfo())).toBe(true);
    } finally {
      window.matchMedia = original;
    }
  });
});
