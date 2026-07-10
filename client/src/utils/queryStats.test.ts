import { describe, expect, it } from "vitest";
import { formatBucketLabel } from "./queryStats";

describe("formatBucketLabel", () => {
  it("leaves a year period unchanged", () => {
    expect(formatBucketLabel("2026", "year")).toBe("2026");
  });

  it("renders a month period as short month + 2-digit year", () => {
    expect(formatBucketLabel("2026-07", "month")).toBe("Jul 26");
  });

  it("renders a day period as MM-DD", () => {
    expect(formatBucketLabel("2026-07-10", "day")).toBe("07-10");
  });

  it("renders a week period (the Monday date) as MM-DD", () => {
    expect(formatBucketLabel("2026-07-06", "week")).toBe("07-06");
  });
});
