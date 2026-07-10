import { BgColorsOutlined } from "@ant-design/icons";
import { Button, Collapse, ColorPicker, Slider, Space, Tooltip, Typography } from "antd";
import { useTranslation } from "react-i18next";

export interface ColorSimilarityValue {
  /** Hex color without a leading '#'. */
  colorHex: string;
  /** Similarity tolerance 0-100 (0 = exact match). */
  threshold: number;
}

const DEFAULT_THRESHOLD = 20;

// A hand-picked palette of common filament colours. One tap + the default tolerance is
// enough for most searches; the full picker stays available behind "Advanced".
const PRESET_COLORS = [
  "#000000", // black
  "#ffffff", // white
  "#9e9e9e", // grey
  "#c0c0c0", // silver
  "#d32f2f", // red
  "#ff9800", // orange
  "#ffeb3b", // yellow
  "#4caf50", // green
  "#009688", // teal
  "#2196f3", // blue
  "#9c27b0", // purple
  "#e91e63", // pink
  "#795548", // brown
  "#e8dcc0", // natural
  "#d4af37", // gold
  "#00bcd4", // cyan
];

/**
 * Toolbar control exposing the backend colour-similarity filter (issue #46). Renders as a
 * single colour-swatch button; the panel leads with common filament colours (one click to
 * filter), the tolerance slider and clear action below, and the full colour picker folded
 * behind an "Advanced" section for exact-hex needs. While a filter is active the toolbar
 * button shows the picked colour so the state is visible at a glance.
 */
export function ColorSimilarityFilter({
  value,
  onChange,
}: {
  value: ColorSimilarityValue | undefined;
  onChange: (value: ColorSimilarityValue | undefined) => void;
}) {
  const { t } = useTranslation();
  const active = value !== undefined;

  const pick = (hexWithHash: string) =>
    onChange({ colorHex: hexWithHash.replace("#", ""), threshold: value?.threshold ?? DEFAULT_THRESHOLD });

  return (
    <ColorPicker
      format="hex"
      value={value ? `#${value.colorHex}` : undefined}
      onChangeComplete={(color) =>
        onChange({ colorHex: color.toHex(), threshold: value?.threshold ?? DEFAULT_THRESHOLD })
      }
      panelRender={(panel) => (
        <div style={{ width: 234 }}>
          <Space direction="vertical" style={{ width: "100%" }} size={8}>
            <Typography.Text type="secondary">{t("colorFilter.help")}</Typography.Text>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(8, 1fr)", gap: 6 }}>
              {PRESET_COLORS.map((hex) => {
                const selected = active && `#${value.colorHex}`.toLowerCase() === hex.toLowerCase();
                return (
                  <button
                    key={hex}
                    type="button"
                    aria-label={hex}
                    onClick={() => pick(hex)}
                    style={{
                      width: 22,
                      height: 22,
                      padding: 0,
                      borderRadius: 4,
                      cursor: "pointer",
                      background: hex,
                      border: selected ? "2px solid #1677ff" : "1px solid rgba(128,128,128,0.4)",
                    }}
                  />
                );
              })}
            </div>
            <div>
              <Typography.Text type="secondary">{t("colorFilter.threshold")}</Typography.Text>
              <Slider
                min={0}
                max={100}
                value={value?.threshold ?? DEFAULT_THRESHOLD}
                onChange={(threshold) => value && onChange({ ...value, threshold })}
                disabled={!active}
              />
            </div>
            <Collapse
              size="small"
              ghost
              items={[
                {
                  key: "advanced",
                  label: t("colorFilter.advanced"),
                  children: panel,
                },
              ]}
            />
            <Button size="small" block onClick={() => onChange(undefined)} disabled={!active}>
              {t("buttons.clear")}
            </Button>
          </Space>
        </div>
      )}
    >
      <Tooltip title={t("colorFilter.title")}>
        <Button
          icon={
            active ? (
              <span
                aria-label={t("colorFilter.title")}
                style={{
                  display: "inline-block",
                  width: 14,
                  height: 14,
                  borderRadius: 3,
                  verticalAlign: "text-top",
                  background: `#${value.colorHex}`,
                  border: "1px solid rgba(128,128,128,0.5)",
                }}
              />
            ) : (
              <BgColorsOutlined />
            )
          }
          type={active ? "primary" : "default"}
        >
          {t("colorFilter.button")}
        </Button>
      </Tooltip>
    </ColorPicker>
  );
}
