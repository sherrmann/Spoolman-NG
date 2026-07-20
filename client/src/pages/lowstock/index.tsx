import { useList, useTranslate } from "@refinedev/core";
import { List } from "@refinedev/antd";
import { Button, Card, Empty, Spin, Tooltip, Typography } from "antd";
import { useNavigate } from "react-router";
import { useLowStockFallbackG } from "../../utils/settings";
import { formatWeight } from "../../utils/parsing";
import { computeLowStock, getFilamentName, LowStockRow } from "../home/analytics";
import { IFilament } from "../filaments/model";
import { IOrder } from "../orders/model";
import { OrderedPill } from "../orders/orderPill";
import { openOrdersByFilament } from "./openOrders";
import { ThresholdEdit } from "./thresholdEdit";
import "./lowstock.css";

const { Text } = Typography;

type OpenOrderMap = Map<number, { order_id: number; shop_name?: string }>;
type Translate = ReturnType<typeof useTranslate>;

function LowStockRowItem({
  row,
  orderMap,
  t,
  navigate,
}: {
  row: LowStockRow;
  orderMap: OpenOrderMap;
  t: Translate;
  navigate: (path: string) => void;
}) {
  const { filament, remaining, threshold, onOrder } = row;
  const hex = "#" + (filament.color_hex ?? "555555").replace("#", "");
  const order = onOrder ? orderMap.get(filament.id) : undefined;

  return (
    <Card size="small" hoverable onClick={() => navigate(`/filament/show/${filament.id}`)}>
      <div className="lowstock-row">
        <div className="lowstock-row-left">
          <div className="lowstock-color-dot" style={{ backgroundColor: hex }} />
          <div className="lowstock-info">
            <Text strong>{getFilamentName(filament)}</Text>
            <div className="lowstock-material">{filament.material ?? "?"}</div>
          </div>
        </div>
        <div className="lowstock-row-right" onClick={(e) => e.stopPropagation()}>
          {onOrder ? (
            <OrderedPill
              onOrder={onOrder}
              shopName={order?.shop_name}
              orderHref={`/orders?highlight=${onOrder.order_id}`}
            />
          ) : (
            // US1 "Mark as ordered" per-row action — wired in Task 10. Disabled here so this
            // read-only page doesn't promise functionality that doesn't exist yet.
            <Tooltip title={t("lowstock.coming_soon")}>
              <Button size="small" disabled>
                {t("lowstock.mark_ordered")}
              </Button>
            </Tooltip>
          )}
          <div className="lowstock-weight">
            {formatWeight(remaining, 0)} <span className="total">/ {formatWeight(threshold, 0)}</span>
          </div>
          <ThresholdEdit filamentId={filament.id} value={filament.low_stock_threshold} />
        </div>
      </div>
    </Card>
  );
}

function LowStockSection({
  rows,
  subhead,
  orderMap,
  t,
  navigate,
}: {
  rows: LowStockRow[];
  subhead: string;
  orderMap: OpenOrderMap;
  t: Translate;
  navigate: (path: string) => void;
}) {
  if (rows.length === 0) return null;
  return (
    <div>
      <div className="lowstock-section-subhead">{subhead}</div>
      <div className="lowstock-list">
        {rows.map((row) => (
          <LowStockRowItem key={row.filament.id} row={row} orderMap={orderMap} t={t} navigate={navigate} />
        ))}
      </div>
    </div>
  );
}

/**
 * Low Stock full page (#298 redesign) — the same merged per-filament list as the dashboard tab
 * (home/index.tsx), in a larger full-page layout with sections, inline threshold edit, and the
 * Ordered pill. Also hosts the placeholder region for the US1 "Mark as ordered" per-row action
 * and the US2 multi-select "Create order" button, both wired in Task 10.
 */
export const LowStockPage = () => {
  const t = useTranslate();
  const navigate = useNavigate();
  const fallbackG = useLowStockFallbackG();

  const filaments = useList<IFilament>({ resource: "filament", pagination: { mode: "off" } });
  const orders = useList<IOrder>({ resource: "order", pagination: { mode: "off" } });

  const allFilaments = filaments.result?.data ?? [];
  const lowStock = computeLowStock(allFilaments, fallbackG);
  const orderMap = openOrdersByFilament(orders.result?.data ?? []);
  const isLoading = filaments.query.isLoading;

  return (
    <List
      title={t("lowstock.title")}
      headerButtons={() => (
        // US2 multi-select "Create order" — wired in Task 10. Disabled here (no row-selection UI
        // exists yet) so this read-only page doesn't promise functionality that doesn't exist yet.
        <Tooltip title={t("lowstock.coming_soon")}>
          <Button disabled>{t("lowstock.create_order")}</Button>
        </Tooltip>
      )}
    >
      {isLoading ? (
        // Avoid flashing empty sections while the filament list is still loading.
        <div className="lowstock-loading">
          <Spin size="large" />
        </div>
      ) : lowStock.count === 0 ? (
        <Empty description={t("lowstock.empty")} />
      ) : (
        <div className="lowstock-page">
          <LowStockSection
            rows={lowStock.explicit}
            subhead={t("lowstock.section.explicit")}
            orderMap={orderMap}
            t={t}
            navigate={navigate}
          />
          <LowStockSection
            rows={lowStock.fallback}
            subhead={t("lowstock.section.fallback", { grams: fallbackG })}
            orderMap={orderMap}
            t={t}
            navigate={navigate}
          />
        </div>
      )}
    </List>
  );
};

export default LowStockPage;
