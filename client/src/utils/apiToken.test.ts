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

  it("forgets the new interface's stored assistant conversation on logout", () => {
    setApiToken("abc");
    localStorage.setItem("spoolman.chat.v1", '{"messages":[],"bubbles":[]}');
    clearApiToken();
    expect(localStorage.getItem("spoolman.chat.v1")).toBeNull();
  });

  it("forgets the stored conversation when a different token is stored, not when the same one is", () => {
    setApiToken("alice");
    localStorage.setItem("spoolman.chat.v1", "{}");
    setApiToken("alice");
    expect(localStorage.getItem("spoolman.chat.v1")).toBe("{}");
    setApiToken("bob");
    expect(localStorage.getItem("spoolman.chat.v1")).toBeNull();
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
