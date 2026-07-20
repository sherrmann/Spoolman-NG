import { useInvalidate, useList, useTranslate } from "@refinedev/core";
import { Checkbox, InputNumber, message, Modal, Select, Spin, Switch, Typography } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../../utils/authReloadHandler";
import { getAPIURL } from "../../utils/url";
import { getFilamentName } from "../home/analytics";
import { IFilament } from "../filaments/model";
import { ILocation } from "../locations/model";
import { IOrder } from "./model";
import "./orders.css";

const { Text } = Typography;

// One order line as the dialog sees it: the user's editable delivered `quantity` (defaulting to
// `outstanding`, the full remaining count on the line) and whether it's checked at all.
export interface ArriveLineInput {
  line_id: number;
  quantity: number;
  outstanding: number;
  selected: boolean;
}

/**
 * Pure POST /order/{id}/arrive body builder (#298 US3). A delivered quantity below a line's
 * outstanding count splits it (quantity included); a full delivery omits `quantity` so the whole
 * line simply gets an `arrived_at`. Unselected or zero-quantity lines are dropped entirely —
 * omitting `lines` on the wire means "arrive everything", which isn't what an unchecked row means.
 */
export function buildArriveBody(
  lines: ArriveLineInput[],
  createSpools: boolean,
  locationId?: number,
): { lines: { line_id: number; quantity?: number }[]; create_spools: boolean; location_id?: number } {
  const out = lines
    .filter((l) => l.selected && l.quantity > 0)
    .map((l) => (l.quantity >= l.outstanding ? { line_id: l.line_id } : { line_id: l.line_id, quantity: l.quantity }));
  const body: { lines: { line_id: number; quantity?: number }[]; create_spools: boolean; location_id?: number } = {
    lines: out,
    create_spools: createSpools,
  };
  if (locationId !== undefined) body.location_id = locationId;
  return body;
}

interface RowState {
  selected: boolean;
  quantity: number;
}

interface Props {
  open: boolean;
  // The order to arrive lines from. Callers that already hold the full order (the Orders list)
  // can pass it directly; the spool-create banner only knows an id (from `filament.on_order`) and
  // relies on the `order` fallback list fetch below to resolve it.
  order?: IOrder;
  orderId?: number;
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * US3 split-arrival dialog (#298): a row per order line — a checkbox, the filament name, and (for
 * still-outstanding lines) a quantity `InputNumber` defaulting to the full outstanding count, with
 * a live "N of M outstanding" label and a split preview once the delivered amount is lowered.
 * Already-arrived lines render disabled with a ✓ and no input. `create_spools` (default on) and an
 * optional location sit below the list; submit POSTs `buildArriveBody`'s output to
 * /order/{id}/arrive and invalidates the order, filament, and spool lists so the Orders state pill,
 * the Low Stock pills, and the spool count all pick up the change. Matches
 * ui-review/orders-mock-D-arrival-split.png.
 *
 * Opened two ways: the Orders page's per-row "Arrived…" action (passes `order` directly — it
 * already has the full list loaded), and the spool-create "on order" banner (onOrderBanner.tsx,
 * passes only `orderId` — the order list fetched here resolves it).
 */
export function ArriveModal({ open, order: orderProp, orderId, onClose, onSuccess }: Props) {
  const t = useTranslate();
  const invalidate = useInvalidate();

  // Only fetched when no order was handed down directly (the banner case) — the Orders page
  // already has the list loaded, so this reuses that cache instead of re-fetching.
  const needsOrderFetch = orderProp === undefined;
  const orders = useList<IOrder>({
    resource: "order",
    pagination: { mode: "off" },
    queryOptions: { enabled: needsOrderFetch },
  });
  const order = orderProp ?? (orders.result?.data ?? []).find((o) => o.id === orderId);

  const filaments = useList<IFilament>({ resource: "filament", pagination: { mode: "off" } });
  const filamentsById = useMemo(
    () => new Map((filaments.result?.data ?? []).map((f) => [f.id, f])),
    [filaments.result?.data],
  );

  const locations = useList<ILocation>({ resource: "locations", pagination: { mode: "off" } });

  const [rows, setRows] = useState<Record<number, RowState>>({});
  const [createSpools, setCreateSpools] = useState(true);
  const [locationId, setLocationId] = useState<number | undefined>(undefined);
  const [submitting, setSubmitting] = useState(false);
  // Guards the open:false->true transition only (same convention as createOrderModal.tsx's
  // wasOpenRef) — a background refetch of the order/filament/location lists while the dialog stays
  // open must not reset the toggle/location or wipe rows the user already edited.
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setCreateSpools(true);
      setLocationId(undefined);
      setRows({});
    }
    wasOpenRef.current = open;
  }, [open]);

  // Seeds a row (selected, quantity = full outstanding) the first time each outstanding line is
  // seen. Keyed by presence-in-map rather than re-running wholesale, so this tolerates `order`
  // arriving after the open transition (the banner's fetch) without clobbering anything the user
  // has already typed on a later re-render.
  useEffect(() => {
    if (!open || !order) return;
    setRows((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const line of order.lines) {
        if (line.arrived_at) continue;
        if (!(line.id in next)) {
          next[line.id] = { selected: true, quantity: line.quantity };
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [open, order]);

  const orderLabel = order ? (order.order_number ?? `#${order.id}`) : "";

  const lineInputs: ArriveLineInput[] = order
    ? order.lines
        .filter((l) => !l.arrived_at)
        .map((l) => {
          const row = rows[l.id] ?? { selected: true, quantity: l.quantity };
          return { line_id: l.id, quantity: row.quantity, outstanding: l.quantity, selected: row.selected };
        })
    : [];
  const canSubmit = lineInputs.some((l) => l.selected && l.quantity > 0);

  const handleSubmit = async () => {
    if (!order) return;
    const body = buildArriveBody(lineInputs, createSpools, locationId);
    setSubmitting(true);
    try {
      const response = await apiFetch(`${getAPIURL()}/order/${order.id}/arrive`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error("Failed to mark arrived");
      invalidate({ resource: "order", invalidates: ["list"] });
      invalidate({ resource: "filament", invalidates: ["list"] });
      invalidate({ resource: "spool", invalidates: ["list"] });
      setSubmitting(false);
      onSuccess();
      onClose();
    } catch {
      setSubmitting(false);
      message.error(t("orders.arrive_error"));
    }
  };

  return (
    <Modal
      title={order ? t("orders.arrive_title", { number: orderLabel }) : t("orders.title")}
      open={open}
      onCancel={onClose}
      onOk={handleSubmit}
      okText={t("orders.mark_arrived")}
      okButtonProps={{ disabled: !canSubmit }}
      confirmLoading={submitting}
      destroyOnClose
    >
      {!order ? (
        <div className="arrive-loading">
          <Spin />
        </div>
      ) : (
        <>
          <Text type="secondary">{t("orders.arrive_subtitle")}</Text>
          <div className="arrive-lines">
            {order.lines.map((line) => {
              const filament = filamentsById.get(line.filament_id);
              const name = filament ? getFilamentName(filament) : `#${line.filament_id}`;

              if (line.arrived_at) {
                return (
                  <div key={line.id} className="arrive-line arrive-line-disabled">
                    <Checkbox checked disabled />
                    <span className="arrive-line-name">{name}</span>
                    <span className="arrive-line-check">✓ {t("orders.arrived_check")}</span>
                  </div>
                );
              }

              const row = rows[line.id] ?? { selected: true, quantity: line.quantity };
              const outstanding = line.quantity;
              const delivered = row.quantity;
              return (
                <div key={line.id} className="arrive-line">
                  <Checkbox
                    checked={row.selected}
                    onChange={(e) =>
                      setRows((prev) => ({ ...prev, [line.id]: { ...row, selected: e.target.checked } }))
                    }
                  />
                  <span className="arrive-line-name">{name}</span>
                  <InputNumber
                    min={1}
                    max={outstanding}
                    value={delivered}
                    disabled={!row.selected}
                    onChange={(v) => setRows((prev) => ({ ...prev, [line.id]: { ...row, quantity: v ?? 1 } }))}
                  />
                  <span className="arrive-line-outstanding">{t("orders.n_of_m", { delivered, outstanding })}</span>
                  {row.selected && delivered < outstanding && (
                    <div className="arrive-split-preview">
                      {t("orders.split_preview", { delivered, rest: outstanding - delivered })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div className="arrive-create-spools">
            <Switch checked={createSpools} onChange={setCreateSpools} />
            <span>{t("orders.create_spools")}</span>
          </div>
          <div className="arrive-location">
            <Text>{t("orders.location")}</Text>
            <Select
              allowClear
              style={{ width: "100%" }}
              value={locationId}
              onChange={(v) => setLocationId(v ?? undefined)}
              loading={locations.query.isLoading}
              options={(locations.result?.data ?? []).map((l) => ({ label: l.name, value: l.id }))}
            />
          </div>
        </>
      )}
    </Modal>
  );
}

export default ArriveModal;
