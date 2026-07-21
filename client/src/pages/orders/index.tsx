import { PlusOutlined } from "@ant-design/icons";
import { List } from "@refinedev/antd";
import { useList, useTranslate } from "@refinedev/core";
import { Button, Empty, Table, Tag } from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { DATE_FORMAT } from "../../utils/dateFormat";
import { IFilament } from "../filaments/model";
import { ArriveModal } from "./arriveModal";
import { IOrder } from "./model";
import { NewOrderModal } from "./newOrderModal";
import { OrderDetailsModal } from "./orderDetailsModal";
import { summarizeLines } from "./ordersState";
import "./orders.css";

/**
 * Orders list page (#298; gate-feedback items #4/#5): order #, shop, ordered date, a lines
 * summary with arrived counts, and the derived state pill. Every row is clickable and opens the
 * read/edit details modal (orderDetailsModal.tsx) — the old antd Table row-expander is gone in
 * favor of that modal. The order # cell is plain text (gate-feedback: it used to also be an
 * external link when the order had a URL, which meant clicking it opened a new tab *and* the
 * modal at once) — the modal itself renders the URL as its own link, so the cell doesn't need to.
 * The per-row "Arrived…" action still opens the Task 11 arrive dialog (arriveModal.tsx) directly,
 * without going through the details modal.
 * The "New order" button opens the from-scratch builder (#324, newOrderModal.tsx) — a filament
 * picker + lines editor over the same header surface as the details modal. Orders can also still be
 * born from the Low Stock flows (mark-as-ordered / bulk create).
 */
export const OrdersPage = () => {
  const t = useTranslate();

  const orders = useList<IOrder>({ resource: "order", pagination: { mode: "off" } });
  // Lines only carry filament_id (#298 API) — hydrate names client-side for the details modal.
  const filaments = useList<IFilament>({ resource: "filament", pagination: { mode: "off" } });

  const allOrders = orders.result?.data ?? [];
  const isLoading = orders.query.isLoading;
  const filamentsById = useMemo(
    () => new Map((filaments.result?.data ?? []).map((f) => [f.id, f])),
    [filaments.result?.data],
  );

  // The Task 11 arrive dialog (US3), opened per-row from the "Arrived…" action below. Mounted
  // only while an order is actually being arrived, matching the mark-ordered/bulk dialogs'
  // conditional-mount convention.
  const [arrivingOrder, setArrivingOrder] = useState<IOrder | undefined>();
  // The details/edit modal (gate-feedback item #5), opened by clicking anywhere on a row.
  const [detailsOrder, setDetailsOrder] = useState<IOrder | undefined>();
  // The from-scratch "New order" builder (#324), opened by the header button below.
  const [creating, setCreating] = useState(false);

  return (
    <List
      title={t("orders.title")}
      headerButtons={() => (
        // Opens the from-scratch order builder (#324). Filaments are already loaded on this page for
        // the details modal, so hand them straight to the builder's picker.
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
          {t("orders.new_order")}
        </Button>
      )}
    >
      {!isLoading && allOrders.length === 0 ? (
        <Empty description={t("orders.empty")} />
      ) : (
        <Table<IOrder>
          rowKey="id"
          dataSource={allOrders}
          loading={isLoading}
          pagination={false}
          rowClassName={(record) => `orders-row-clickable${record.state === "arrived" ? " orders-row-arrived" : ""}`}
          onRow={(record) => ({ onClick: () => setDetailsOrder(record) })}
          columns={[
            {
              title: t("orders.order_number"),
              dataIndex: "order_number",
              key: "order_number",
              // Plain text, not a link (gate-feedback): the row's onClick already opens the
              // details modal, which shows the order's URL as its own link — a link here too
              // meant clicking the order # both opened a new tab *and* the modal.
              render: (_, record) => record.order_number ?? `#${record.id}`,
            },
            {
              title: t("orders.shop"),
              key: "shop",
              render: (_, record) => record.shop?.name ?? "—",
            },
            {
              title: t("orders.ordered_at"),
              key: "ordered_at",
              // Date-only per the approved mock — the ordered date doesn't need a time-of-day.
              render: (_, record) => dayjs(record.ordered_at).format(DATE_FORMAT),
            },
            {
              title: t("orders.lines_summary_title"),
              key: "lines_summary",
              render: (_, record) => {
                const s = summarizeLines(record);
                return `${t("orders.lines_summary", { arrived: s.arrived, total: s.total })} · ${t(
                  "orders.filaments_count",
                  { count: s.filaments },
                )}`;
              },
            },
            {
              title: t("orders.state_title"),
              key: "state",
              render: (_, record) => {
                const s = summarizeLines(record);
                return (
                  <Tag color={record.state === "open" ? "blue" : "green"}>
                    {record.state === "open"
                      ? t("orders.state.open", { count: s.outstanding })
                      : t("orders.state.arrived")}
                  </Tag>
                );
              },
            },
            {
              key: "actions",
              render: (_, record) =>
                record.state === "open" ? (
                  <Button
                    size="small"
                    onClick={(e) => {
                      // The row itself is now clickable (opens the details modal below) — this
                      // action must not also trigger that when clicked.
                      e.stopPropagation();
                      setArrivingOrder(record);
                    }}
                  >
                    {t("orders.arrived_action")}
                  </Button>
                ) : null,
            },
          ]}
        />
      )}
      {arrivingOrder && (
        <ArriveModal
          open
          order={arrivingOrder}
          onClose={() => setArrivingOrder(undefined)}
          onSuccess={() => setArrivingOrder(undefined)}
        />
      )}
      {detailsOrder && (
        <OrderDetailsModal
          open
          order={detailsOrder}
          filamentsById={filamentsById}
          onClose={() => setDetailsOrder(undefined)}
          onSuccess={() => setDetailsOrder(undefined)}
        />
      )}
      {creating && (
        <NewOrderModal
          open
          filaments={filaments.result?.data ?? []}
          onClose={() => setCreating(false)}
          onSuccess={() => setCreating(false)}
        />
      )}
    </List>
  );
};

export default OrdersPage;
