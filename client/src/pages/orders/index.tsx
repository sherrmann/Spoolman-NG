import { PlusOutlined } from "@ant-design/icons";
import { List } from "@refinedev/antd";
import { useList, useTranslate } from "@refinedev/core";
import { Button, Empty, Table, Tag, Tooltip } from "antd";
import dayjs from "dayjs";
import { useMemo } from "react";
import { DATE_TIME_FORMAT_SHORT } from "../../utils/dateFormat";
import { getFilamentName } from "../home/analytics";
import { IFilament } from "../filaments/model";
import { IOrder, IOrderLine } from "./model";
import { summarizeLines } from "./ordersState";
import "./orders.css";

/** Per-line detail shown when an order row is expanded: filament name + arrived state (✓ / outstanding). */
function OrderLinesDetail({ lines, filamentsById }: { lines: IOrderLine[]; filamentsById: Map<number, IFilament> }) {
  const t = useTranslate();
  return (
    <ul className="orders-lines-detail">
      {lines.map((line) => {
        const filament = filamentsById.get(line.filament_id);
        const label = filament ? getFilamentName(filament) : `#${line.filament_id}`;
        return (
          <li key={line.id} className={line.arrived_at ? "orders-line-arrived" : undefined}>
            {label} × {line.quantity} — {line.arrived_at ? `✓ ${t("orders.state.arrived")}` : t("orders.outstanding")}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Orders list page (#298): order #, shop, ordered date, a lines summary with arrived counts, and
 * the derived state pill. The "New order" button and the per-row "Arrived…" action are stubs —
 * wired to the Task 10 create-order modal and the Task 11 arrive modal, respectively.
 */
export const OrdersPage = () => {
  const t = useTranslate();

  const orders = useList<IOrder>({ resource: "order", pagination: { mode: "off" } });
  // Lines only carry filament_id (#298 API) — hydrate names client-side for the expanded detail.
  const filaments = useList<IFilament>({ resource: "filament", pagination: { mode: "off" } });

  const allOrders = orders.result?.data ?? [];
  const isLoading = orders.query.isLoading;
  const filamentsById = useMemo(
    () => new Map((filaments.result?.data ?? []).map((f) => [f.id, f])),
    [filaments.result?.data],
  );

  return (
    <List
      title={t("orders.title")}
      headerButtons={() => (
        // Opens the create-order flow — wired to the Task 10 modal. Disabled here so this
        // read-only page doesn't promise functionality that doesn't exist yet.
        <Tooltip title={t("orders.coming_soon")}>
          <Button type="primary" icon={<PlusOutlined />} disabled>
            {t("orders.new_order")}
          </Button>
        </Tooltip>
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
          rowClassName={(record) => (record.state === "arrived" ? "orders-row-arrived" : "")}
          expandable={{
            expandedRowRender: (record) => <OrderLinesDetail lines={record.lines} filamentsById={filamentsById} />,
            rowExpandable: (record) => record.lines.length > 0,
          }}
          columns={[
            {
              title: t("orders.order_number"),
              dataIndex: "order_number",
              key: "order_number",
              render: (_, record) => {
                const label = record.order_number ?? `#${record.id}`;
                return record.url ? (
                  <a href={record.url} target="_blank" rel="noreferrer noopener">
                    {label}
                  </a>
                ) : (
                  label
                );
              },
            },
            {
              title: t("orders.shop"),
              key: "shop",
              render: (_, record) => record.shop?.name ?? "—",
            },
            {
              title: t("orders.ordered_at"),
              key: "ordered_at",
              render: (_, record) => dayjs(record.ordered_at).format(DATE_TIME_FORMAT_SHORT),
            },
            {
              title: t("orders.lines_summary_title", "Lines"),
              key: "lines_summary",
              render: (_, record) => {
                const s = summarizeLines(record);
                return t("orders.lines_summary", { arrived: s.arrived, total: s.total, filaments: s.filaments });
              },
            },
            {
              title: t("orders.state_title", "State"),
              key: "state",
              render: (_, record) => (
                <Tag color={record.state === "open" ? "blue" : "green"}>{t(`orders.state.${record.state}`)}</Tag>
              ),
            },
            {
              key: "actions",
              render: (_, record) =>
                record.state === "open" ? (
                  // Opens the Task 11 arrive modal — the handler is a marked stub in this task.
                  <Tooltip title={t("orders.coming_soon")}>
                    <Button size="small" disabled>
                      {t("orders.arrived_action")}
                    </Button>
                  </Tooltip>
                ) : null,
            },
          ]}
        />
      )}
    </List>
  );
};

export default OrdersPage;
