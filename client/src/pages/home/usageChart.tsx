import { useTranslate } from "@refinedev/core";
import { Segmented, Tooltip } from "antd";
import { useState } from "react";
import { formatWeight } from "../../utils/parsing";
import { UsageBucket, formatBucketLabel, useUsageStats } from "../../utils/queryStats";
import { useCurrencyFormatter } from "../../utils/settings";

const BUCKETS: UsageBucket[] = ["day", "week", "month", "year"];
// Keep the chart readable: only the most recent N buckets are plotted.
const MAX_BARS = 12;

/**
 * Home "Usage" tab (#81): a dependency-free bar chart of filament consumed per time bucket, driven
 * by the additive /stats/usage endpoint. Bars are plain divs (matching the dashboard's other charts)
 * so no charting library is pulled in. A granularity selector switches day/week/month/year; a
 * per-bar tooltip surfaces the exact weight and estimated cost.
 */
export const UsageChart = ({ barColor, trackColor }: { barColor: string; trackColor: string }) => {
  const t = useTranslate();
  const currencyFormatter = useCurrencyFormatter();
  const [bucket, setBucket] = useState<UsageBucket>("month");
  const { data, isLoading } = useUsageStats(bucket);

  const recent = (data ?? []).slice(-MAX_BARS);
  const maxWeight = Math.max(1, ...recent.map((s) => s.consumed_weight));
  const totalWeight = recent.reduce((sum, s) => sum + s.consumed_weight, 0);
  const totalCost = recent.reduce((sum, s) => sum + s.cost, 0);

  return (
    <div className="usage-chart-wrap">
      <div className="usage-chart-toolbar">
        <Segmented
          size="small"
          value={bucket}
          onChange={(v) => setBucket(v as UsageBucket)}
          options={BUCKETS.map((b) => ({ label: t(`home.usage.bucket.${b}`), value: b }))}
        />
        {recent.length > 0 && (
          <span className="usage-chart-summary">
            {formatWeight(totalWeight, 0)}
            {totalCost > 0 ? ` · ${currencyFormatter.format(totalCost)}` : ""}
          </span>
        )}
      </div>
      {isLoading ? (
        <div className="dash-empty">{t("home.usage.loading", "Loading...")}</div>
      ) : recent.length === 0 ? (
        <div className="dash-empty">{t("home.usage.empty")}</div>
      ) : (
        <div className="usage-chart">
          {recent.map((s) => {
            const heightPct = (s.consumed_weight / maxWeight) * 100;
            return (
              <Tooltip
                key={s.period}
                title={
                  <>
                    <div>{s.period}</div>
                    <div>{formatWeight(s.consumed_weight, 1)}</div>
                    {s.cost > 0 && <div>{currencyFormatter.format(s.cost)}</div>}
                  </>
                }
              >
                <div className="usage-chart-col">
                  <div className="usage-chart-track" style={{ background: trackColor }}>
                    <div
                      className="usage-chart-bar"
                      style={{ height: `${Math.max(heightPct, 2)}%`, backgroundColor: barColor }}
                    />
                  </div>
                  <div className="usage-chart-xlabel">{formatBucketLabel(s.period, bucket)}</div>
                </div>
              </Tooltip>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default UsageChart;
