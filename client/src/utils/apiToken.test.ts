import { afterEach, describe, expect, it } from "vitest";
import { apiAuthHeader, clearApiToken, getApiToken, setApiToken, withWebsocketToken } from "./apiToken";

// Issue #48: client storage and wiring of the optional API bearer token.
describe("apiToken", () => {
  afterEach(() => clearApiToken());

  it("stores and reads the token, and clears it", () => {
    expect(getApiToken()).toBeNull();
    setApiToken("abc");
    expect(getApiToken()).toBe("abc");
    clearApiToken();
    expect(getApiToken()).toBeNull();
  });

  it("builds an Authorization header only when a token is set", () => {
    expect(apiAuthHeader()).toEqual({});
    setApiToken("abc");
    expect(apiAuthHeader()).toEqual({ Authorization: "Bearer abc" });
  });

  it("appends the token to a websocket URL, respecting existing query strings and encoding", () => {
    expect(withWebsocketToken("ws://h/api/v1/spool")).toBe("ws://h/api/v1/spool");
    setApiToken("a b");
    expect(withWebsocketToken("ws://h/api/v1/spool")).toBe("ws://h/api/v1/spool?token=a%20b");
    expect(withWebsocketToken("ws://h/api/v1/spool?x=1")).toBe("ws://h/api/v1/spool?x=1&token=a%20b");
  });
});
