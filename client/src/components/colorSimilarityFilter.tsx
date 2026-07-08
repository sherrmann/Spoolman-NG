import { BgColorsOutlined } from "@ant-design/icons";
import { Button, ColorPicker, Slider, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";

export interface ColorSimilarityValue {
  /** Hex color without a leading '#'. */
  colorHex: string;
  /** Similarity tolerance 0-100 (0 = exact match). */
  threshold: number;
}

const DEFAULT_THRESHOLD = 20;

/**
 * Toolbar control exposing the backend colour-similarity filter (issue #46). Renders as a
 * single colour-swatch button; the tolerance slider and a clear action live inside the same
 * colour panel so nothing extra is added to the toolbar. Emits `undefined` when cleared.
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

  return (
    <ColorPicker
      format="hex"
      value={value ? `#${value.colorHex}` : undefined}
      onChangeComplete={(color) =>
        onChange({ colorHex: color.toHex(), threshold: value?.threshold ?? DEFAULT_THRESHOLD })
      }
      panelRender={(panel) => (
        <div>
          {panel}
          <Space direction="vertical" style={{ width: "100%", marginTop: 8 }}>
            <Typography.Text type="secondary">{t("colorFilter.threshold")}</Typography.Text>
            <Slider
              min={0}
              max={100}
              value={value?.threshold ?? DEFAULT_THRESHOLD}
              onChange={(threshold) => value && onChange({ ...value, threshold })}
              disabled={!active}
            />
            <Button size="small" block onClick={() => onChange(undefined)} disabled={!active}>
              {t("buttons.clear")}
            </Button>
          </Space>
        </div>
      )}
    >
      <Button icon={<BgColorsOutlined />} type={active ? "primary" : "default"}>
        {t("colorFilter.button")}
      </Button>
    </ColorPicker>
  );
}
