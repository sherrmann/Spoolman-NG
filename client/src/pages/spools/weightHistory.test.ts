import { describe, expect, it } from "vitest";
import { SpoolUsageEvent } from "../../utils/queryUsageEvents";
import { maxIdleGain, measureSeries } from "./weightHistory";

function event(over: Partial<SpoolUsageEvent>): SpoolUsageEvent {
  return { id: 1, spool_id: 1, time: "2026-07-01T00:00:00", event_type: "use", delta: 10, ...over };
}

describe("measureSeries", () => {
  it("keeps only measure events with a measured_weight, oldest-first", () => {
    const events: SpoolUsageEvent[] = [
      event({ time: "2026-07-03T00:00:00", event_type: "measure", measured_weight: 800 }),
      event({ time: "2026-07-02T00:00:00", event_type: "use", delta: 50 }),
      event({ time: "2026-07-01T00:00:00", event_type: "measure", measured_weight: 900 }),
    ];
    expect(measureSeries(events)).toEqual([
      { time: "2026-07-01T00:00:00", weight: 900 },
      { time: "2026-07-03T00:00:00", weight: 800 },
    ]);
  });

  it("ignores measure events without a measured_weight", () => {
    const events: SpoolUsageEvent[] = [event({ event_type: "measure" })];
    expect(measureSeries(events)).toEqual([]);
  });

  it("returns an empty series when there are no measurements", () => {
    expect(measureSeries([event({}), event({ event_type: "update" })])).toEqual([]);
  });
});

describe("maxIdleGain", () => {
  it("is 0 for a monotonically decreasing (normal consumption) series", () => {
    expect(
      maxIdleGain([
        { time: "a", weight: 900 },
        { time: "b", weight: 800 },
        { time: "c", weight: 750 },
      ]),
    ).toBe(0);
  });

  it("reports the largest upward jump between consecutive measurements", () => {
    // 900 -> 830 (down) -> 845 (+15) -> 840 (down): the max gain is 15.
    const series = [
      { time: "a", weight: 900 },
      { time: "b", weight: 830 },
      { time: "c", weight: 845 },
      { time: "d", weight: 840 },
    ];
    expect(maxIdleGain(series)).toBe(15);
  });

  it("is 0 for a series with fewer than two points", () => {
    expect(maxIdleGain([{ time: "a", weight: 900 }])).toBe(0);
    expect(maxIdleGain([])).toBe(0);
  });
});
