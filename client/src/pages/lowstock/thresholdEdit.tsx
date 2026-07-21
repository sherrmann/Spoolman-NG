import { useInvalidate, useTranslate, useUpdate } from "@refinedev/core";
import { Button, InputNumber, Popover } from "antd";
import { useState } from "react";
import { formatWeight } from "../../utils/parsing";

/**
 * Low-stock-threshold editor on every Low Stock row (#298 redesign; gate-feedback item #3): an
 * explicit "Adjust threshold" button opens the same edit popover the old inline pencil did. A
 * filament with its own threshold set shows the current value on the button itself ("Threshold:
 * 500 g"); a row only caught by the global fallback shows the bare "Adjust threshold" label,
 * since it has no explicit value yet. Shared by both surfaces — the dashboard Low Stock tab
 * (home/index.tsx) and the full Low Stock page (lowstock/index.tsx) — so they stay consistent.
 */
export function ThresholdEdit({ filamentId, value }: { filamentId: number; value?: number }) {
  const t = useTranslate();
  const { mutate } = useUpdate();
  const invalidate = useInvalidate();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<number | null>(value ?? null);

  const save = () => {
    mutate(
      { resource: "filament", id: filamentId, values: { low_stock_threshold: draft }, successNotification: false },
      { onSuccess: () => invalidate({ resource: "filament", invalidates: ["list"] }) },
    );
    setOpen(false);
  };

  const label =
    value != null
      ? t("low_stock.threshold_button_value", { value: formatWeight(value, 0) })
      : t("low_stock.threshold_button");

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (next) setDraft(value ?? null);
        setOpen(next);
      }}
      trigger="click"
      content={
        <InputNumber
          autoFocus
          min={0}
          value={draft}
          addonAfter="g"
          onChange={setDraft}
          onPressEnter={save}
          onBlur={save}
        />
      }
    >
      <Button size="small" onClick={(e) => e.stopPropagation()}>
        {label}
      </Button>
    </Popover>
  );
}
