// #294 client wiring for the native self-update. The POST body shape (tag vs. latest) and the
// error-message surfacing are the parts worth pinning; the modal that consumes this is covered by
// updateModal.test.tsx.
import { afterEach, describe, expect, it, vi } from "vitest";
import { triggerUpdate, useUpdateModal } from "./updateAction";

describe("triggerUpdate (#294)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("POSTs an empty body to /update for a latest-release update and returns the result", async () => {
    const fetchMock = vi.fn(
      async () =>
        ({
          ok: true,
          status: 202,
          json: async () => ({ status: "started", target: null, restart_managed: true }),
        }) as unknown as Response,
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await triggerUpdate();

    expect(result.restart_managed).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toMatch(/\/update$/);
    expect(init.method).toBe("POST");
    expect(init.body).toBe("{}");
  });

  it("includes the tag when one is given", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({}) }) as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);

    await triggerUpdate("v2026.7.20");

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.body).toBe(JSON.stringify({ tag: "v2026.7.20" }));
  });

  it("throws the server's detail message on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () => ({ ok: false, status: 403, json: async () => ({ detail: "disabled" }) }) as unknown as Response,
      ),
    );
    await expect(triggerUpdate()).rejects.toThrow("disabled");
  });
});

describe("useUpdateModal store (#294)", () => {
  it("shows and closes the shared modal", () => {
    useUpdateModal.getState().close();
    expect(useUpdateModal.getState().open).toBe(false);
    useUpdateModal.getState().show();
    expect(useUpdateModal.getState().open).toBe(true);
    useUpdateModal.getState().close();
    expect(useUpdateModal.getState().open).toBe(false);
  });
});
