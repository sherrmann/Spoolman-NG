import { afterEach, describe, expect, it, vi } from "vitest";
import { setSpoolArchived, useSpoolFilament, useSpoolFilamentMeasure } from "./functions";
import { ISpool } from "./model";

// The spool write helpers (archive, adjust via /use and /measure) must go through the
// authenticated transport: with SPOOLMAN_API_TOKEN or user accounts configured, a bare fetch
// without the Authorization header 401s on every write (#224).

vi.mock("../../utils/url", () => ({ getAPIURL: () => "http://test/api/v1" }));

const spool = { id: 7 } as ISpool;

function captureFetch() {
  const calls: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit) => {
      const url = input instanceof Request ? input.url : String(input);
      calls.push({ url, init });
      return { ok: true } as Response;
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.removeItem("spoolmanApiToken");
});

describe("spool write helpers attach the API token (#224)", () => {
  it("setSpoolArchived sends Authorization on the PATCH", async () => {
    localStorage.setItem("spoolmanApiToken", "sekrit-224");
    const calls = captureFetch();

    await setSpoolArchived(spool, true);

    const headers = (calls[0].init.headers ?? {}) as Record<string, string>;
    expect(calls[0].url).toContain("/spool/7");
    expect(headers.Authorization).toBe("Bearer sekrit-224");
  });

  it("useSpoolFilament sends Authorization on the PUT to /use", async () => {
    localStorage.setItem("spoolmanApiToken", "sekrit-224");
    const calls = captureFetch();

    await useSpoolFilament(spool, undefined, 5);

    const headers = (calls[0].init.headers ?? {}) as Record<string, string>;
    expect(calls[0].url).toContain("/spool/7/use");
    expect(headers.Authorization).toBe("Bearer sekrit-224");
  });

  it("useSpoolFilamentMeasure sends Authorization on the PUT to /measure", async () => {
    localStorage.setItem("spoolmanApiToken", "sekrit-224");
    const calls = captureFetch();

    await useSpoolFilamentMeasure(spool, 1050);

    const headers = (calls[0].init.headers ?? {}) as Record<string, string>;
    expect(calls[0].url).toContain("/spool/7/measure");
    expect(headers.Authorization).toBe("Bearer sekrit-224");
  });

  it("sends no Authorization header when no token is stored", async () => {
    const calls = captureFetch();

    await setSpoolArchived(spool, false);

    const headers = (calls[0].init.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });
});

// #227: the write helpers must surface HTTP failures. They used to swallow any non-ok
// response, so the adjust modal closed as success on a server 400 and the user believed
// the measurement was recorded.
describe("spool write helpers surface HTTP errors (#227)", () => {
  it("setSpoolArchived throws the server message on a non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 400, json: async () => ({ message: "nope" }) }) as unknown as Response),
    );

    await expect(setSpoolArchived(spool, true)).rejects.toThrow("nope");
  });

  it("useSpoolFilamentMeasure throws the server message on a 400", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          ({
            ok: false,
            status: 400,
            json: async () => ({ message: "Initial weight is not set." }),
          }) as unknown as Response,
      ),
    );

    await expect(useSpoolFilamentMeasure(spool, 1050)).rejects.toThrow("Initial weight is not set.");
  });

  it("useSpoolFilament falls back to a generic error when the body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          ({
            ok: false,
            status: 502,
            json: async () => {
              throw new SyntaxError("not json");
            },
          }) as unknown as Response,
      ),
    );

    await expect(useSpoolFilament(spool, undefined, 5)).rejects.toThrow("HTTP 502");
  });
});
