import { useTranslate } from "@refinedev/core";
import { Alert, Button } from "antd";
import { useState } from "react";
import { ArriveModal } from "./arriveModal";

// The subset of a filament (or filament select-option) the banner needs — just the on_order
// pointer surfaced by functions.tsx's useGetFilamentSelectOptions mapping.
interface OnOrderFilament {
  on_order?: { order_id: number; ordered_at: string };
}

/**
 * Spool-create banner (#298 US3): when the filament picked on the spool-create form is on an open
 * order, offers to complete that order's outstanding line right from here instead of clicking away
 * to the Orders page first. Opens the same ArriveModal used there, scoped to the filament's
 * `on_order.order_id` (the modal fetches the order itself from just the id).
 */
export function OnOrderBanner({ filament }: { filament: OnOrderFilament | null | undefined }) {
  const t = useTranslate();
  const [open, setOpen] = useState(false);
  const onOrder = filament?.on_order;

  if (!onOrder) return null;

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t("orders.banner", { id: onOrder.order_id })}
        action={
          <Button size="small" onClick={() => setOpen(true)}>
            {t("orders.mark_arrived")}
          </Button>
        }
      />
      {open && (
        <ArriveModal open orderId={onOrder.order_id} onClose={() => setOpen(false)} onSuccess={() => setOpen(false)} />
      )}
    </>
  );
}

export default OnOrderBanner;
