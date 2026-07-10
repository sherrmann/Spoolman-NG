import { afterEach, describe, expect, it, vi } from "vitest";
import { clearApiToken, getApiToken } from "./apiToken";
import { login } from "./auth";

describe("login (#52)", () => {
  afterEach(() => {
    clearApiToken();
    vi.unstubAllGlobals();
  });

  it("stores the returned access token so it is applied to every transport", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ access_token: "tok-123" }) }) as unknown as Response),
    );
    await login("alice", "pw");
    expect(getApiToken()).toBe("tok-123");
  });

  it("throws the server's message on a failed login", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          ({ ok: false, json: async () => ({ detail: "Invalid username or password." }) }) as unknown as Response,
      ),
    );
    await expect(login("alice", "bad")).rejects.toThrow("Invalid username or password.");
    expect(getApiToken()).toBeNull();
  });
});
