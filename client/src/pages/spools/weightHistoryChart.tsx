import { useTranslate } from "@refinedev/core";
import { Alert, theme } from "antd";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import { DATE_TIME_FORMAT_SHORT } from "../../utils/dateFormat";
import { IDLE_GAIN_THRESHOLD_G, WeightPoint, maxIdleGain } from "./weightHistory";

dayjs.extend(utc);

// A compact, dependency-free SVG line chart of a spool's measured gross weight over time (#104).
// Uses a viewBox so it scales to the container width. Renders nothing for fewer than two points.
const VIEW_W = 600;
const VIEW_H = 160;
const PAD = { top: 12, right: 12, bottom: 12, left: 48 };

export const WeightHistoryChart = ({ series }: { series: WeightPoint[] }) => {
  const t = useTranslate();
  const { token } = theme.useToken();

  if (series.length < 2) {
    return null;
  }

  const weights = series.map((p) => p.weight);
  const minW = Math.min(...weights);
  const maxW = Math.max(...weights);
  const span = maxW - minW || 1;
  const innerW = VIEW_W - PAD.left - PAD.right;
  const innerH = VIEW_H - PAD.top - PAD.bottom;

  const x = (i: number) => PAD.left + (i / (series.length - 1)) * innerW;
  const y = (w: number) => PAD.top + innerH - ((w - minW) / span) * innerH;

  const points = series.map((p, i) => `${x(i)},${y(p.weight)}`).join(" ");
  const gain = maxIdleGain(series);
  const showGainHint = gain >= IDLE_GAIN_THRESHOLD_G;

  return (
    <div>
      {showGainHint && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={t("spool.weight_history.idle_gain", { grams: gain.toFixed(1) })}
        />
      )}
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        width="100%"
        role="img"
        aria-label={t("spool.weight_history.chart_label", "Measured weight over time")}
        style={{ color: token.colorTextSecondary }}
      >
        <text x={PAD.left - 6} y={y(maxW) + 4} textAnchor="end" fontSize="10" fill="currentColor" opacity="0.7">
          {Math.round(maxW)}
        </text>
        <text x={PAD.left - 6} y={y(minW) + 4} textAnchor="end" fontSize="10" fill="currentColor" opacity="0.7">
          {Math.round(minW)}
        </text>
        <line x1={PAD.left} y1={y(maxW)} x2={VIEW_W - PAD.right} y2={y(maxW)} stroke="currentColor" opacity="0.15" />
        <line x1={PAD.left} y1={y(minW)} x2={VIEW_W - PAD.right} y2={y(minW)} stroke="currentColor" opacity="0.15" />
        <polyline
          points={points}
          fill="none"
          stroke={token.colorPrimary}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {series.map((p, i) => (
          <circle key={p.time + i} cx={x(i)} cy={y(p.weight)} r="3" fill={token.colorPrimary}>
            <title>{`${dayjs.utc(p.time).local().format(DATE_TIME_FORMAT_SHORT)}: ${p.weight.toFixed(1)} g`}</title>
          </circle>
        ))}
      </svg>
    </div>
  );
};

export default WeightHistoryChart;
