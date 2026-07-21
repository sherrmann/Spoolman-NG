import {
  AppstoreOutlined,
  AreaChartOutlined,
  DatabaseOutlined,
  EnvironmentOutlined,
  ExperimentOutlined,
  HighlightOutlined,
  PlusOutlined,
  ShopOutlined,
  ShoppingOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { useList, useNavigation, useTranslate } from "@refinedev/core";
import { Button, Result, Space, Tabs, theme, Tooltip } from "antd";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import utc from "dayjs/plugin/utc";
import { useContext, useState } from "react";
import { Trans } from "react-i18next";
import { Link, useNavigate } from "react-router";
import SpoolIcon from "../../components/spoolIcon";
import { ColorModeContext } from "../../contexts/color-mode";
import { formatWeight, formatWeightCompact } from "../../utils/parsing";
import { getSpoolEffectiveColor } from "../../utils/spoolColor";
import { useCurrencyFormatter, useLowStockFallbackG } from "../../utils/settings";
import { IFilament } from "../filaments/model";
import { ISpool } from "../spools/model";
import { IVendor } from "../vendors/model";
import { IOrder } from "../orders/model";
import { openOrdersByFilament } from "../lowstock/openOrders";
import { MarkOrderedDialog } from "../orders/markOrderedDialog";
import { OrderedPill } from "../orders/orderPill";
import { ThresholdEdit } from "../lowstock/thresholdEdit";
import {
  computeLowStock,
  distinctMaterialCount,
  getFilamentName,
  getSpoolName,
  locationBreakdown,
  materialBreakdown,
  recentSpools as computeRecentSpools,
  STALE_ALERT_DAYS,
  STALE_WARN_DAYS,
  staleSpools,
  registeredWithinDays,
  totalRemainingWeight as computeTotalRemainingWeight,
  totalValue as computeTotalValue,
  vendorBreakdown,
} from "./analytics";
import { UsageChart } from "./usageChart";
import "./home.css";

dayjs.extend(utc);
dayjs.extend(relativeTime);

const { useToken } = theme;

// Dark surface palette — works on top of the app's existing dark background
export const Home = () => {
  const { token } = useToken();
  const { mode } = useContext(ColorModeContext);
  const isDark = mode === "dark";

  const S = isDark
    ? { lowest: "#1a1a1a", low: "#1f1f1f", base: "#252525", high: "#2a2a2a", highest: "#313131" }
    : { lowest: "#f5f5f5", low: "#ffffff", base: "#fafafa", high: "#f0f0f0", highest: "#d9d9d9" };
  const t = useTranslate();
  const navigate = useNavigate();
  const { showUrl } = useNavigation();
  const currencyFormatter = useCurrencyFormatter();
  // US1 "Mark as ordered" (#298 Task 10) — the dialog is only mounted while a filament is picked,
  // so its data hooks (useShops' useQuery, refine's useCreate) never run on a plain dashboard view.
  const [markOrderedFilament, setMarkOrderedFilament] = useState<IFilament | undefined>();

  const spoolsAll = useList<ISpool>({
    resource: "spool",
    pagination: { mode: "off" },
    meta: { queryParams: { allow_archived: false } },
  });
  const filaments = useList<IFilament>({
    resource: "filament",
    pagination: { pageSize: 1 },
  });
  // All filaments (with their server-computed stock aggregates) drive the per-filament shopping
  // list (#109 / #116). Kept separate from the count-only query above.
  const filamentsAll = useList<IFilament>({
    resource: "filament",
    pagination: { mode: "off" },
  });
  const vendors = useList<IVendor>({
    resource: "vendor",
    pagination: { pageSize: 1 },
  });

  const allSpools = spoolsAll.result?.data ?? [];
  const allFilaments = filamentsAll.result?.data ?? [];
  const hasSpools = allSpools.length > 0;
  const isLoading = spoolsAll.query.isLoading;
  const isError = spoolsAll.query.isError;

  // --- Calculations (pure logic lives in ./analytics, unit-tested there) ---
  const totalRemainingWeight = computeTotalRemainingWeight(allSpools);
  const totalValue = computeTotalValue(allSpools);
  const fallbackG = useLowStockFallbackG();
  const lowStock = computeLowStock(allFilaments, fallbackG);
  const hasLowStock = lowStock.count > 0;
  const openOrders = useList<IOrder>({ resource: "order", pagination: { mode: "off" } });
  const orderMap = openOrdersByFilament(openOrders.result?.data ?? []);
  const recentSpools = computeRecentSpools(allSpools);
  const staleList = staleSpools(allSpools);
  const materialBreakdownData = materialBreakdown(allSpools);
  const locationBreakdownData = locationBreakdown(allSpools, t("locations.no_location"));
  const vendorBreakdownData = vendorBreakdown(allSpools);
  const topVendor = vendorBreakdownData[0]?.[0] ?? "-";

  const matColors: Record<string, string> = isDark
    ? {
        PLA: "#81ecff",
        "PLA+": "#00e3fd",
        PETG: "#6ded00",
        ABS: "#ff7350",
        "ABS+": "#ff9070",
        ASA: "#eb2f96",
        TPU: "#b388ff",
        "TPU 95A": "#b388ff",
        "PETG-CF": "#00bcd4",
        nGen: "#ff5252",
      }
    : {
        PLA: "#0891b2",
        "PLA+": "#0e7490",
        PETG: "#16a34a",
        ABS: "#ea580c",
        "ABS+": "#f97316",
        ASA: "#c026d3",
        TPU: "#7c3aed",
        "TPU 95A": "#7c3aed",
        "PETG-CF": "#0d9488",
        nGen: "#dc2626",
      };

  if (isLoading) {
    return (
      <div className="dashboard" style={{ paddingTop: 64, textAlign: "center", opacity: 0.3 }}>
        {t("loading")}
      </div>
    );
  }

  if (isError) {
    return (
      <div className="dashboard">
        <Result
          status="error"
          title={t("home.load_error_title", "Failed to load spools")}
          subTitle={t("home.load_error_desc", "There was a problem loading your spools. Please try again.")}
          extra={
            <Button type="primary" onClick={() => spoolsAll.query.refetch()}>
              {t("buttons.refresh")}
            </Button>
          }
        />
      </div>
    );
  }

  if (!hasSpools) {
    return (
      <div className="dashboard empty-hero">
        <div className="empty-hero-icon" style={{ background: token.colorPrimary }}>
          <DatabaseOutlined style={{ fontSize: 40, color: "#fff" }} />
        </div>
        <h2 className="empty-hero-title">{t("home.welcome")}</h2>
        <p className="empty-hero-desc">
          <Trans i18nKey="home.description" components={{ helpPageLink: <Link to="/help" /> }} />
        </p>
        <Button
          type="primary"
          size="large"
          icon={<PlusOutlined />}
          onClick={() => navigate("/spool/create")}
          className="empty-hero-btn"
        >
          {t("spool.titles.create")}
        </Button>
      </div>
    );
  }

  return (
    <div className="dashboard">
      {/* Header: just the create-action cluster — the nav already says where we are, so the
          page skips a redundant "Home" title and goes straight to the KPIs. */}
      <div className="dashboard-header">
        <div className="dash-create-group">
          <span className="dash-create-label">{t("buttons.create")}</span>
          <Space.Compact>
            <Tooltip title={t("home.create.spool")}>
              <Button type="primary" icon={<DatabaseOutlined />} onClick={() => navigate("/spool/create")} />
            </Tooltip>
            <Tooltip title={t("home.create.filament")}>
              <Button type="primary" icon={<HighlightOutlined />} onClick={() => navigate("/filament/create")} />
            </Tooltip>
            <Tooltip title={t("home.create.vendor")}>
              <Button type="primary" icon={<ShopOutlined />} onClick={() => navigate("/vendor/create")} />
            </Tooltip>
          </Space.Compact>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="kpi-grid">
        <Link to="/spool" className="kpi-card" style={{ background: S.low }}>
          <DatabaseOutlined className="kpi-bg-icon" />
          <div className="kpi-label">{t("spool.spool")}</div>
          <div className="kpi-value">{allSpools.length}</div>
          <div className="kpi-footer" style={{ color: isDark ? "#6ded00" : "#16a34a" }}>
            <span>
              +{registeredWithinDays(allSpools, 30)} {t("home.kpi.this_month")}
            </span>
          </div>
        </Link>

        <Link to="/filament" className="kpi-card" style={{ background: S.low }}>
          <HighlightOutlined className="kpi-bg-icon" />
          <div className="kpi-label">{t("filament.filament")}</div>
          <div className="kpi-value">{filaments.result?.total ?? 0}</div>
          <div className="kpi-footer" style={{ color: isDark ? "#00e3fd" : "#0891b2" }}>
            <span>{t("home.kpi.materials", { count: distinctMaterialCount(allFilaments) })}</span>
          </div>
        </Link>

        <Link to="/vendor" className="kpi-card" style={{ background: S.low }}>
          <ShopOutlined className="kpi-bg-icon" />
          <div className="kpi-label">{t("vendor.vendor")}</div>
          <div className="kpi-value">{vendors.result?.total ?? 0}</div>
          <div className="kpi-footer" style={{ opacity: 0.4 }}>
            {t("home.kpi.top")}: {topVendor}
          </div>
        </Link>

        <Link to="/spool" className="kpi-card" style={{ background: S.low }}>
          <ShoppingOutlined className="kpi-bg-icon" />
          <div className="kpi-label">{t("home.total_weight")}</div>
          <div className="kpi-value">
            {formatWeight(totalRemainingWeight, 1).split(" ")[0]}{" "}
            <span className="kpi-unit">{formatWeight(totalRemainingWeight, 1).split(" ")[1]}</span>
          </div>
          <div
            className="kpi-footer"
            style={{
              color: lowStock.count > 0 ? "#ff716c" : undefined,
              opacity: lowStock.count > 0 ? 1 : 0.4,
            }}
          >
            {lowStock.count > 0 ? (
              <>
                <WarningOutlined /> {lowStock.count} {t("home.low_stock").toUpperCase()}
              </>
            ) : (
              <span>
                {t("home.total_value")}: {currencyFormatter.format(totalValue)}
              </span>
            )}
          </div>
        </Link>
      </div>

      {/* Main content area */}
      <div className="dashboard-main">
        {/* Left Column — Tabs */}
        <Tabs
          defaultActiveKey={hasLowStock ? "lowstock" : "materials"}
          items={[
            {
              key: "lowstock",
              label: (
                <span>
                  {hasLowStock && <WarningOutlined style={{ color: "#ff716c" }} />} {t("home.low_stock")}
                </span>
              ),
              children: (
                <div className="dash-section" style={{ background: S.low }}>
                  {lowStock.count === 0 ? (
                    <div className="dash-empty">{t("home.all_stocked")}</div>
                  ) : (
                    <>
                      {[["explicit", lowStock.explicit] as const, ["fallback", lowStock.fallback] as const].map(
                        ([reason, rows]) =>
                          rows.length === 0 ? null : (
                            <div key={reason}>
                              <div className="dash-section-subhead" style={{ opacity: 0.5 }}>
                                {reason === "explicit"
                                  ? t("low_stock.section.explicit")
                                  : t("low_stock.section.fallback", { grams: fallbackG })}
                              </div>
                              <div className="low-stock-list">
                                {rows.map(({ filament, remaining, onOrder }) => {
                                  const hex = "#" + (filament.color_hex ?? "555555").replace("#", "");
                                  const order = onOrder ? orderMap.get(filament.id) : undefined;
                                  return (
                                    <div
                                      key={filament.id}
                                      className="low-stock-item"
                                      style={{ background: S.lowest }}
                                      onClick={() => navigate(showUrl("filament", filament.id))}
                                    >
                                      <div className="low-stock-left">
                                        <div
                                          className="low-stock-color-dot"
                                          style={{
                                            backgroundColor: hex,
                                            boxShadow: isDark ? `0 0 14px ${hex}50` : `0 1px 3px rgba(0,0,0,0.12)`,
                                          }}
                                        />
                                        <div className="low-stock-info">
                                          <h4>{getFilamentName(filament)}</h4>
                                          <p>
                                            {t("spool.fields.material")}: {filament.material ?? "?"}
                                          </p>
                                        </div>
                                      </div>
                                      <div className="low-stock-right" onClick={(e) => e.stopPropagation()}>
                                        {onOrder ? (
                                          <OrderedPill
                                            onOrder={onOrder}
                                            shopName={order?.shop_name}
                                            orderHref={`/orders?highlight=${onOrder.order_id}`}
                                          />
                                        ) : (
                                          <Button size="small" onClick={() => setMarkOrderedFilament(filament)}>
                                            {t("orders.mark_ordered")}
                                          </Button>
                                        )}
                                        {/* Remaining only, rendered as "<amount> left" (gate-feedback
                                            round: parity with the Low Stock page — dropped the
                                            "/ threshold" suffix and the previously-hardcoded red).
                                            Red while actionable, grey once on order — same
                                            .actionable/.on-order semantics as lowstock.css. */}
                                        <div className={`low-stock-weight ${onOrder ? "on-order" : "actionable"}`}>
                                          {t("low_stock.remaining_left", { amount: formatWeightCompact(remaining) })}
                                        </div>
                                        <ThresholdEdit filamentId={filament.id} value={filament.low_stock_threshold} />
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          ),
                      )}
                    </>
                  )}
                </div>
              ),
            },
            {
              key: "swatches",
              label: (
                <span>
                  <AppstoreOutlined /> {t("home.all_spools")}
                </span>
              ),
              children: (
                <div className="dash-section" style={{ background: S.low }}>
                  {allSpools.length === 0 ? (
                    <div className="dash-empty">{t("home.no_spools")}</div>
                  ) : (
                    <div className="swatch-grid">
                      {allSpools.map((spool) => (
                        <Tooltip key={spool.id} title={getSpoolName(spool)}>
                          <div className="swatch-grid-item" onClick={() => navigate(showUrl("spool", spool.id))}>
                            <SpoolIcon color={getSpoolEffectiveColor(spool)} size="large" no_margin />
                          </div>
                        </Tooltip>
                      ))}
                    </div>
                  )}
                </div>
              ),
            },
            {
              key: "materials",
              label: (
                <span>
                  <ExperimentOutlined /> {t("home.by_material")}
                </span>
              ),
              children: (
                <div className="dash-section" style={{ background: S.low }}>
                  <div className="material-list">
                    {materialBreakdownData.map(([material, data]) => {
                      const maxWeight = materialBreakdownData[0]?.[1].weight || 1;
                      const pct = (data.weight / maxWeight) * 100;
                      const color = matColors[material] ?? "#81ecff";
                      return (
                        <div key={material}>
                          <div className="material-header">
                            <span className="material-name">{material}</span>
                            <span className="material-weight">{formatWeight(data.weight, 0)}</span>
                          </div>
                          <div className="material-bar" style={{ background: S.highest }}>
                            <div
                              className="material-bar-fill"
                              style={{
                                width: `${pct}%`,
                                backgroundColor: color,
                                boxShadow: isDark ? `0 0 12px ${color}40` : "none",
                              }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ),
            },
            {
              key: "vendors",
              label: (
                <span>
                  <ShopOutlined /> {t("home.by_vendor")}
                </span>
              ),
              children: (
                <div className="dash-section" style={{ background: S.low }}>
                  <div className="material-list">
                    {vendorBreakdownData.map(([vendor, count], idx) => {
                      const maxCount = vendorBreakdownData[0]?.[1] || 1;
                      const pct = (count / maxCount) * 100;
                      let barColor: string;
                      if (idx === 0) {
                        barColor = isDark ? "#81ecff" : "#0891b2";
                      } else if (idx < 3) {
                        barColor = isDark ? "#6ded00" : "#16a34a";
                      } else {
                        barColor = isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.2)";
                      }
                      return (
                        <div key={vendor}>
                          <div className="material-header">
                            <span className="material-name">{vendor}</span>
                            <span className="material-weight">
                              {count} {t("spool.spool")}
                            </span>
                          </div>
                          <div className="material-bar" style={{ background: S.highest }}>
                            <div
                              className="material-bar-fill"
                              style={{
                                width: `${pct}%`,
                                backgroundColor: barColor,
                                boxShadow: isDark ? `0 0 12px ${barColor}40` : "none",
                              }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ),
            },
            {
              key: "usage",
              label: (
                <span>
                  <AreaChartOutlined /> {t("home.usage.tab")}
                </span>
              ),
              children: (
                <div className="dash-section" style={{ background: S.low }}>
                  <UsageChart barColor={token.colorPrimary} trackColor={S.highest} />
                </div>
              ),
            },
          ]}
        />

        {/* Right Column — Recently Used + Locations */}
        <div className="dash-right-col">
          <div className="dash-right-section" style={{ background: S.low }}>
            <div className="dash-section-header">
              <h3 className="dash-section-title">{t("home.recently_used")}</h3>
            </div>
            {recentSpools.length === 0 ? (
              <div className="dash-empty">{t("home.no_recent")}</div>
            ) : (
              <div className="timeline-list">
                {recentSpools.map((spool, idx) => {
                  const isFirst = idx === 0;
                  return (
                    <div key={spool.id} className="timeline-item" onClick={() => navigate(showUrl("spool", spool.id))}>
                      <div
                        className={"timeline-dot" + (isFirst ? " active" : "")}
                        style={{
                          backgroundColor: isFirst
                            ? token.colorPrimary
                            : isDark
                              ? "rgba(255,255,255,0.12)"
                              : "rgba(0,0,0,0.1)",
                          color: isFirst ? token.colorPrimary : undefined,
                        }}
                      />
                      <div>
                        <div className="timeline-time">{dayjs(spool.last_used).fromNow()}</div>
                        <div className="timeline-name">{getSpoolName(spool)}</div>
                        <div className="timeline-detail">
                          {spool.filament.material ?? ""} · {formatWeight(spool.remaining_weight ?? 0, 0)} ·{" "}
                          {spool.location || t("locations.no_location")}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="dash-right-section" style={{ background: S.low }}>
            <div className="dash-section-header">
              <h3 className="dash-section-title">{t("home.gathering_dust")}</h3>
            </div>
            {staleList.length === 0 ? (
              <div className="dash-empty">{t("home.no_stale")}</div>
            ) : (
              <div className="timeline-list">
                {staleList.map(({ spool, staleSince, neverUsed }) => {
                  const days = dayjs().diff(dayjs(staleSince), "day");
                  const ageColor =
                    days >= STALE_ALERT_DAYS
                      ? token.colorError
                      : days >= STALE_WARN_DAYS
                        ? token.colorWarning
                        : undefined;
                  return (
                    <div key={spool.id} className="timeline-item" onClick={() => navigate(showUrl("spool", spool.id))}>
                      <div
                        className="timeline-dot"
                        style={{
                          backgroundColor: ageColor ?? (isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.1)"),
                        }}
                      />
                      <div>
                        <div className="timeline-time" style={{ color: ageColor }}>
                          {neverUsed
                            ? `${t("home.never_used")} · ${dayjs(staleSince).fromNow()}`
                            : dayjs(staleSince).fromNow()}
                        </div>
                        <div className="timeline-name">{getSpoolName(spool)}</div>
                        <div className="timeline-detail">
                          {spool.filament.material ?? ""} · {formatWeight(spool.remaining_weight ?? 0, 0)} ·{" "}
                          {spool.location || t("locations.no_location")}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="dash-right-section" style={{ background: S.low }}>
            <div className="dash-section-header">
              <h3 className="dash-section-title">
                <EnvironmentOutlined />
                {t("home.by_location")}
              </h3>
            </div>
            <div className="location-list">
              {locationBreakdownData.map(([location, count], idx) => {
                let badgeBg: string;
                let badgeColor: string;
                if (idx === 0) {
                  badgeBg = isDark ? "rgba(129, 236, 255, 0.1)" : "rgba(8, 145, 178, 0.1)";
                  badgeColor = isDark ? "#00e3fd" : "#0891b2";
                } else if (idx < 3) {
                  badgeBg = isDark ? "rgba(109, 237, 0, 0.08)" : "rgba(22, 163, 74, 0.1)";
                  badgeColor = isDark ? "#6ded00" : "#16a34a";
                } else {
                  badgeBg = isDark ? "rgba(255, 255, 255, 0.04)" : "rgba(0, 0, 0, 0.04)";
                  badgeColor = isDark ? "rgba(255, 255, 255, 0.35)" : "rgba(0, 0, 0, 0.4)";
                }
                return (
                  <div
                    key={location}
                    className="location-item"
                    style={{ background: S.high }}
                    onClick={() => navigate("/locations")}
                  >
                    <span className="location-name">{location}</span>
                    <span className="location-badge" style={{ background: badgeBg, color: badgeColor }}>
                      {count} {t("spool.spool")}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
      {/* Mounted only while a filament is picked (not always-mounted-but-closed): its data hooks
          (useShops' react-query useQuery, refine's useCreate) would otherwise run on every plain
          dashboard render, which the boundary tests in index.test.tsx don't provide for (no
          QueryClient, and @refinedev/core is mocked without useCreate there). */}
      {markOrderedFilament && (
        <MarkOrderedDialog
          open
          filament={markOrderedFilament}
          onClose={() => setMarkOrderedFilament(undefined)}
          onSuccess={() => setMarkOrderedFilament(undefined)}
        />
      )}
    </div>
  );
};

export default Home;
