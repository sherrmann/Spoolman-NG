import { useList, useTranslate } from "@refinedev/core";
import { List } from "@refinedev/antd";
import { Button, Card, Checkbox, Empty, Space, Spin, Typography } from "antd";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { useLowStockFallbackG } from "../../utils/settings";
import { formatWeightCompact } from "../../utils/parsing";
import { computeLowStock, getFilamentName, LowStockRow } from "../home/analytics";
import { IFilament } from "../filaments/model";
import { IOrder } from "../orders/model";
import { CreateOrderModal } from "../orders/createOrderModal";
import { MarkOrderedDialog } from "../orders/markOrderedDialog";
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
  selected,
  onToggleSelect,
  onMarkOrdered,
  t,
  navigate,
}: {
  row: LowStockRow;
  orderMap: OpenOrderMap;
  selected: boolean;
  onToggleSelect: (filamentId: number) => void;
  onMarkOrdered: (filament: IFilament) => void;
  t: Translate;
  navigate: (path: string) => void;
}) {
  const { filament, remaining, onOrder } = row;
  const hex = "#" + (filament.color_hex ?? "555555").replace("#", "");
  const order = onOrder ? orderMap.get(filament.id) : undefined;

  return (
    <Card size="small" hoverable onClick={() => navigate(`/filament/show/${filament.id}`)}>
      <div className="lowstock-row">
        <div className="lowstock-row-left">
          {/* Slot always renders (even empty) so the dot/name lines up the same whether or not a
              checkbox is present — an already-ordered row can't be added to another order, so it
              has none (gate-feedback item #1). */}
          <div className="lowstock-checkbox-slot">
            {!onOrder && (
              <Checkbox
                checked={selected}
                onClick={(e) => e.stopPropagation()}
                onChange={() => onToggleSelect(filament.id)}
                aria-label={getFilamentName(filament)}
              />
            )}
          </div>
          <div className="lowstock-color-dot" style={{ backgroundColor: hex }} />
          <div className="lowstock-info">
            <Text strong>{getFilamentName(filament)}</Text>
            <div className="lowstock-material">{filament.material ?? "?"}</div>
          </div>
        </div>
        <div className="lowstock-row-right" onClick={(e) => e.stopPropagation()}>
          <div className="lowstock-action-col">
            {onOrder ? (
              <OrderedPill
                onOrder={onOrder}
                shopName={order?.shop_name}
                orderHref={`/orders?highlight=${onOrder.order_id}`}
              />
            ) : (
              <Button size="small" onClick={() => onMarkOrdered(filament)}>
                {t("orders.mark_ordered")}
              </Button>
            )}
          </div>
          {/* Remaining weight only — the threshold now lives on the "Adjust threshold" button
              instead (gate-feedback item #2/#3). Rendered as "<amount> left" (gate-feedback
              round: i18n `low_stock.remaining_left`) with the amount human-formatted via
              formatWeightCompact. Red while actionable, grey once on order. */}
          <div className={`lowstock-weight ${onOrder ? "on-order" : "actionable"}`}>
            {t("low_stock.remaining_left", { amount: formatWeightCompact(remaining) })}
          </div>
          <div className="lowstock-threshold-col">
            <ThresholdEdit filamentId={filament.id} value={filament.low_stock_threshold} />
          </div>
        </div>
      </div>
    </Card>
  );
}

function LowStockSection({
  rows,
  subhead,
  orderMap,
  selected,
  onToggleSelect,
  onMarkOrdered,
  t,
  navigate,
}: {
  rows: LowStockRow[];
  subhead: string;
  orderMap: OpenOrderMap;
  selected: Set<number>;
  onToggleSelect: (filamentId: number) => void;
  onMarkOrdered: (filament: IFilament) => void;
  t: Translate;
  navigate: (path: string) => void;
}) {
  if (rows.length === 0) return null;
  return (
    <div>
      <div className="lowstock-section-subhead">{subhead}</div>
      {/* Labels the weight number below as "Remaining" now that the threshold moved onto the
          "Adjust threshold" button, so the bare number stays self-explanatory (gate-feedback
          item #2). Mirrors the row's right-side columns so it lines up above the weight. */}
      <div className="lowstock-columns-header">
        <div className="lowstock-action-col" />
        <span className="lowstock-columns-header-weight">{t("low_stock.remaining_header")}</span>
        <div className="lowstock-threshold-col" />
      </div>
      <div className="lowstock-list">
        {rows.map((row) => (
          <LowStockRowItem
            key={row.filament.id}
            row={row}
            orderMap={orderMap}
            selected={selected.has(row.filament.id)}
            onToggleSelect={onToggleSelect}
            onMarkOrdered={onMarkOrdered}
            t={t}
            navigate={navigate}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * Low Stock full page (#298 redesign) — the same merged per-filament list as the dashboard tab
 * (home/index.tsx), in a larger full-page layout with sections, inline threshold edit, and the
 * Ordered pill. Also hosts the US1 "Mark as ordered" per-row action and the US2 multi-select
 * "Create order" button (Task 10).
 */
export const LowStockPage = () => {
  const t = useTranslate();
  const navigate = useNavigate();
  const fallbackG = useLowStockFallbackG();

  const filaments = useList<IFilament>({ resource: "filament", pagination: { mode: "off" } });
  const orders = useList<IOrder>({ resource: "order", pagination: { mode: "off" } });

  const allFilaments = filaments.result?.data ?? [];
  // Memoized so `lowStock` (and everything derived from it below) keeps its identity across a
  // background refetch that leaves the filament data unchanged — react-query's structural
  // sharing keeps `allFilaments` itself referentially stable in that case, but computeLowStock
  // rebuilds fresh arrays every call, so without this the CreateOrderModal's `rows` prop would
  // get a new (but equal) array on every re-render while the bulk modal is open (#298 review).
  const lowStock = useMemo(() => computeLowStock(allFilaments, fallbackG), [allFilaments, fallbackG]);
  const orderMap = openOrdersByFilament(orders.result?.data ?? []);
  const isLoading = filaments.query.isLoading;

  // US1: the single-filament dialog. US2: the bulk multi-select selection set + its modal. Both
  // dialogs are mounted only while actually open, so their data hooks (useShops' react-query
  // useQuery, refine's useCreate) don't run on a plain read of this page.
  const [markOrderedFilament, setMarkOrderedFilament] = useState<IFilament | undefined>();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);

  const toggleSelect = (filamentId: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(filamentId)) next.delete(filamentId);
      else next.add(filamentId);
      return next;
    });

  // A row that's already on order can't be (re)selected — filtering here also drops any id
  // that was selected and then moved on-order (e.g. via the per-row action) out of the set.
  const selectableRows = useMemo(
    () => [...lowStock.explicit, ...lowStock.fallback].filter((r) => !r.onOrder),
    [lowStock],
  );
  // Memoized on [selection, sections] so the array passed to CreateOrderModal as `rows` keeps a
  // stable identity across unrelated re-renders while the modal is open (#298 review finding).
  const selectedRows = useMemo(
    () => selectableRows.filter((r) => selected.has(r.filament.id)),
    [selectableRows, selected],
  );

  return (
    <List
      title={t("low_stock.title")}
      headerButtons={() => (
        <Space>
          {selectedRows.length > 0 && (
            <Text type="secondary">{t("orders.selected_count", { count: selectedRows.length })}</Text>
          )}
          <Button disabled={selectedRows.length === 0} onClick={() => setBulkOpen(true)}>
            {t("orders.create_order")}
          </Button>
        </Space>
      )}
    >
      {isLoading ? (
        // Avoid flashing empty sections while the filament list is still loading.
        <div className="lowstock-loading">
          <Spin size="large" />
        </div>
      ) : lowStock.count === 0 ? (
        <Empty description={t("low_stock.empty")} />
      ) : (
        <div className="lowstock-page">
          <LowStockSection
            rows={lowStock.explicit}
            subhead={t("low_stock.section.explicit")}
            orderMap={orderMap}
            selected={selected}
            onToggleSelect={toggleSelect}
            onMarkOrdered={setMarkOrderedFilament}
            t={t}
            navigate={navigate}
          />
          <LowStockSection
            rows={lowStock.fallback}
            subhead={t("low_stock.section.fallback", { grams: fallbackG })}
            orderMap={orderMap}
            selected={selected}
            onToggleSelect={toggleSelect}
            onMarkOrdered={setMarkOrderedFilament}
            t={t}
            navigate={navigate}
          />
        </div>
      )}
      {markOrderedFilament && (
        <MarkOrderedDialog
          open
          filament={markOrderedFilament}
          onClose={() => setMarkOrderedFilament(undefined)}
          onSuccess={() => setMarkOrderedFilament(undefined)}
        />
      )}
      {bulkOpen && (
        <CreateOrderModal
          open
          rows={selectedRows}
          onClose={() => setBulkOpen(false)}
          onSuccess={() => {
            setBulkOpen(false);
            setSelected(new Set());
          }}
        />
      )}
    </List>
  );
};

export default LowStockPage;
