import dayjs from "dayjs";
import "dayjs/locale/de";
import "dayjs/locale/en";
import { afterAll, describe, expect, it } from "vitest";
import { DATE_FORMAT, DATE_TIME_FORMAT, DATE_TIME_FORMAT_SHORT } from "./dateFormat";

// A dayjs instance captures the active locale at creation time, and the app sets dayjs.locale() to the
// UI language before any date is rendered — so build the instant AFTER selecting the locale, exactly
// as a render does. The naive local wall-clock string keeps .format() output timezone-independent.
const ISO = "2026-07-08T14:30:05";

describe("locale-aware date formats (#87)", () => {
  afterAll(() => dayjs.locale("en"));

  it("renders the date in the active locale's order via the L token", () => {
    dayjs.locale("de");
    expect(dayjs(ISO).format(DATE_TIME_FORMAT)).toBe("08.07.2026 14:30:05");
    dayjs.locale("en");
    expect(dayjs(ISO).format(DATE_TIME_FORMAT)).toBe("07/08/2026 14:30:05");
  });

  it("keeps an explicit 24-hour clock regardless of locale", () => {
    // US English would use a 12h AM/PM clock for the LTS token; the explicit HH:mm:ss stays 24-hour.
    dayjs.locale("en");
    expect(dayjs(ISO).format(DATE_TIME_FORMAT)).toContain("14:30:05");
  });

  it("drops seconds in the short form", () => {
    dayjs.locale("de");
    expect(dayjs(ISO).format(DATE_TIME_FORMAT_SHORT)).toBe("08.07.2026 14:30");
    dayjs.locale("en");
    expect(dayjs(ISO).format(DATE_TIME_FORMAT_SHORT)).toBe("07/08/2026 14:30");
  });

  it("drops the time entirely in the date-only form", () => {
    dayjs.locale("de");
    expect(dayjs(ISO).format(DATE_FORMAT)).toBe("08.07.2026");
    dayjs.locale("en");
    expect(dayjs(ISO).format(DATE_FORMAT)).toBe("07/08/2026");
  });
});
