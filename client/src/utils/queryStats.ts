import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";
import { apiFetch } from "./authReloadHandler";
import { getAPIURL } from "./url";

// Client access to the additive filament usage-and-cost statistics endpoint (#81), which aggregates
// the spool usage-event log (#50) into time buckets.

export type UsageBucket = "day" | "week" | "month" | "year";

export interface UsageStat {
  /** Bucket label, keyed by its start: YYYY-MM-DD (day/week), YYYY-MM (month) or YYYY (year). */
  period: string;
  /** Net filament consumed in this period, in grams. */
  consumed_weight: number;
  /** Estimated cost of the consumed filament, 0 where price or net weight is unknown. */
  cost: number;
}

/**
 * Shorten a bucket's period label for a chart axis: year stays "YYYY", month becomes "MMM YY"
 * (e.g. "Jul 26"), and day/week become "MM-DD". Pure so it can be unit-tested.
 */
export function formatBucketLabel(period: string, bucket: UsageBucket): string {
  if (bucket === "year") {
    return period;
  }
  if (bucket === "month") {
    return dayjs(`${period}-01`).format("MMM YY");
  }
  return dayjs(period).format("MM-DD");
}

export function useUsageStats(bucket: UsageBucket) {
  return useQuery<UsageStat[]>({
    queryKey: ["stats", "usage", bucket],
    queryFn: async () => {
      const response = await apiFetch(`${getAPIURL()}/stats/usage?bucket=${bucket}`);
      if (!response.ok) {
        throw new Error("Network response was not ok");
      }
      return response.json();
    },
  });
}
