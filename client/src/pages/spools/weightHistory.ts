import { SpoolUsageEvent } from "../../utils/queryUsageEvents";

// Weight-history analysis for the spool page (#104). Derived purely from the existing usage-event
// log (measure events carry a gross measured_weight); no new API or table. Kept as pure functions so
// the series-building and the experimental moisture hint can be unit-tested.

export interface WeightPoint {
  time: string;
  weight: number;
}

/**
 * Chronological (oldest-first) series of measured gross weights, taken from measure events. Events
 * arrive newest-first from the API; this normalises to time order for plotting.
 */
export function measureSeries(events: SpoolUsageEvent[]): WeightPoint[] {
  return events
    .filter((e) => e.event_type === "measure" && typeof e.measured_weight === "number")
    .map((e) => ({ time: e.time, weight: e.measured_weight as number }))
    .sort((a, b) => a.time.localeCompare(b.time));
}

/**
 * Largest increase in measured gross weight between two consecutive measurements, in grams.
 *
 * Filament is only ever consumed, so a measured spool getting *heavier* over time suggests it has
 * absorbed moisture (a refill would too — hence this is surfaced only as an experimental hint, not a
 * hard claim). Returns 0 when the trend is monotonically non-increasing or there are fewer than two
 * measurements.
 */
export function maxIdleGain(series: WeightPoint[]): number {
  let maxGain = 0;
  for (let i = 1; i < series.length; i++) {
    const gain = series[i].weight - series[i - 1].weight;
    if (gain > maxGain) {
      maxGain = gain;
    }
  }
  return maxGain;
}

// Below this many grams, a measured increase is treated as scale noise rather than a moisture hint.
export const IDLE_GAIN_THRESHOLD_G = 2;
