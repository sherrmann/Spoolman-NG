import { EditOutlined } from "@ant-design/icons";
import { useInvalidate, useTranslate, useUpdate } from "@refinedev/core";
import { InputNumber, Popover, Tooltip } from "antd";
import { useState } from "react";

/** Inline low-stock-threshold editor on every Low Stock row (#298 redesign). */
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

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
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
      <Tooltip title={t("lowstock.edit_threshold")}>
        <EditOutlined onClick={(e) => e.stopPropagation()} style={{ opacity: 0.6, cursor: "pointer" }} />
      </Tooltip>
    </Popover>
  );
}
