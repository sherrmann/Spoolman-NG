import {
  AppstoreOutlined,
  EditOutlined,
  EyeOutlined,
  FilterOutlined,
  InboxOutlined,
  LinkOutlined,
  PlusSquareOutlined,
  PrinterOutlined,
  ToolOutlined,
  ToTopOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { List, TextField, useTable } from "@refinedev/antd";
import { LogicalFilter, useInvalidate, useNavigation, useTranslate } from "@refinedev/core";
import { Button, Grid, Input, message, Modal, Pagination, Space, Table, Tooltip } from "antd";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import { HTMLAttributes, Key, useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import {
  Action,
  ActionsColumn,
  CustomFieldColumn,
  DateColumn,
  FilteredQueryColumn,
  NumberColumn,
  SortedColumn,
  SpoolIconColumn,
} from "../../components/column";
import { AISearchButton } from "../../components/aiSearchButton";
import { ColumnManager } from "../../components/columnManager";
import { ColorSimilarityFilter, ColorSimilarityValue, DEFAULT_THRESHOLD } from "../../components/colorSimilarityFilter";
import { AISearchFilters } from "../../utils/queryAI";
import { useLiveify } from "../../components/liveify";
import { NumberFieldUnit } from "../../components/numberField";
import {
  useSpoolmanFilamentFilter,
  useSpoolmanLocations,
  useSpoolmanLotNumbers,
  useSpoolmanMaterials,
  useSpoolmanVendors,
} from "../../components/otherModels";
import { columnIdOf, computeEffectiveOrder, moveInOrder, orderColumns } from "../../utils/columnOrder";
import { removeUndefined } from "../../utils/filtering";
import { getSpoolEffectiveColor } from "../../utils/spoolColor";
import { buildSpoolActionUrl, useSpoolActionLinks } from "../../utils/spoolActionLinks";
import { ResizableHeaderCell } from "../../components/resizableHeaderCell";
import SpoolIcon from "../../components/spoolIcon";
import { enrichText, formatWeight } from "../../utils/parsing";
import { EntityType, useGetFields } from "../../utils/queryFields";
import { TableState, useInitialTableState, useSavedState, useStoreInitialState } from "../../utils/saveload";
import { getCurrencySymbol, useCurrency, useCurrencyFormatter, useUnitScaling } from "../../utils/settings";
import { useLocations } from "../locations/functions";
import { bulkPatchSpools, useSpoolBulkEditModal } from "./bulkEdit";
import { useBulkWeightUpdateModal } from "./bulkWeightUpdate";
import { setSpoolArchived, useSpoolAdjustModal } from "./functions";
import { EditableNumberCell, EditableSelectCell, EditableTextCell } from "../../components/inlineEdit";
import { ISpool } from "./model";
import { SpoolGalleryCard } from "./spoolGalleryCard";

dayjs.extend(utc);

const { confirm } = Modal;

export interface ISpoolCollapsed extends ISpool {
  "filament.combined_name": string; // Eg. "Prusa - PLA Red"
  "filament.id": number;
  "filament.name"?: string | null;
  "filament.material"?: string;
  "filament.vendor.name"?: string | null;
  // Sort-only virtual column (#113): lets the list sort by the filament's colour hue. Never populated
  // on the row (the swatch renders from color_hex/multi_color_hexes); it only names the server sort key.
  "filament.color_hue"?: number | null;
}

function collapseSpool(element: ISpool): ISpoolCollapsed {
  let filament_name: string;
  if (element.filament.vendor && "name" in element.filament.vendor) {
    filament_name = `${element.filament.vendor.name} - ${element.filament.name}`;
  } else {
    filament_name = element.filament.name ?? element.filament.id.toString();
  }
  // The REST list omits `price` when unset (response_model_exclude_none), but websocket
  // live updates send it as `null`. Fall back to the filament price for both cases,
  // otherwise a live update (e.g. after a weight adjust) blanks the price column until reload.
  if (element.price === undefined || element.price === null) {
    element.price = element.filament.price;
  }
  return {
    ...element,
    "filament.combined_name": filament_name,
    "filament.id": element.filament.id,
    "filament.name": element.filament.name ?? null,
    "filament.material": element.filament.material,
    "filament.vendor.name": element.filament.vendor?.name ?? null,
  };
}

function translateColumnI18nKey(columnName: string): string {
  if (columnName === "filament.vendor.name") return "spool.fields.vendor_name";
  if (columnName === "filament.name") return "spool.fields.filament_name_only";
  if (columnName === "filament.color_hue") return "spool.fields.color";
  columnName = columnName.replace(".", "_");
  if (columnName === "filament_combined_name") columnName = "filament_name";
  else if (columnName === "filament_material") columnName = "material";
  return `spool.fields.${columnName}`;
}

const namespace = "spoolList-v2";

const allColumns: (keyof ISpoolCollapsed & string)[] = [
  "id",
  "filament.combined_name",
  "filament.vendor.name",
  "filament.name",
  "filament.material",
  "filament.color_hue",
  "price",
  "used_weight",
  "remaining_weight",
  "spool_weight",
  "used_length",
  "remaining_length",
  "location",
  "lot_nr",
  "first_used",
  "last_used",
  "registered",
  "comment",
];
const defaultColumns = allColumns.filter(
  // Vendor and the standalone filament name are available as opt-in columns for users who prefer the
  // Filament column split into Vendor + Name (#94), but hidden by default so the list stays
  // uncluttered — the default combined name column already shows both. spool_weight is likewise an
  // opt-in column (#115), as is the colour swatch column that sorts by hue (#113) — the combined name
  // column already shows the swatch, so it ships hidden and users enable it to sort by colour.
  (column_id) =>
    [
      "registered",
      "used_length",
      "remaining_length",
      "lot_nr",
      "filament.vendor.name",
      "filament.name",
      "filament.color_hue",
      "spool_weight",
    ].indexOf(column_id) === -1,
);

export const SpoolList = () => {
  const t = useTranslate();
  const invalidate = useInvalidate();
  const navigate = useNavigate();
  const extraFields = useGetFields(EntityType.spool);
  // #83: a filament's own custom fields describe every spool of that filament, so surface them on the
  // spool list too — as opt-in, display-only columns namespaced "filament.extra.<key>" (a spool field
  // and a filament field may share a key). Sorting/filtering by them is deferred (needs a FilamentField
  // cross-join the spool endpoint doesn't have yet), so the columns are read-only.
  const filamentExtraFields = useGetFields(EntityType.filament);
  const filamentColumnLabel = useCallback((name: string) => `${name} (${t("spool.fields.filament")})`, [t]);
  const currencyFormatter = useCurrencyFormatter();
  const currency = useCurrency();
  const unitScaling = useUnitScaling();
  // antd message instance (with its context holder rendered below) for inline edit and
  // adjust/archive error toasts, matching the app's existing message.useMessage() pattern.
  const [messageApi, messageContextHolder] = message.useMessage();

  const { openSpoolAdjustModal, spoolAdjustModal } = useSpoolAdjustModal(messageApi);

  // User-configured per-spool action links (#140), appended to each row's action menu when set.
  const actionLinks = useSpoolActionLinks();

  // Inline cell editing is a pointer-device affordance; gate it to desktop using
  // the same breakpoint mechanism the header uses (Grid.useBreakpoint / !md).
  const screens = Grid.useBreakpoint();
  const inlineEditEnabled = !!screens.md;

  // Location options for the inline Select: existing locations from settings +
  // locations already in use, deduped — mirroring the create/edit spool form.
  const settingsLocations = useLocations();
  const usedLocations = useSpoolmanLocations(true);
  const locationOptions = useMemo(() => {
    const merged = [...(settingsLocations ?? [])];
    (usedLocations.data ?? []).forEach((loc) => {
      if (loc && !merged.includes(loc)) merged.push(loc);
    });
    return merged;
  }, [settingsLocations, usedLocations.data]);

  // Filter-value query hooks for the table columns' filter dropdowns. Call them unconditionally here
  // rather than inline in the columns array (which is only built when the table renders), so switching
  // to grid view — where the table isn't rendered — doesn't change the hook count and violate the
  // Rules of Hooks (#139).
  const filamentFilterQuery = useSpoolmanFilamentFilter();
  const vendorFilterQuery = useSpoolmanVendors();
  const materialFilterQuery = useSpoolmanMaterials();
  const locationFilterQuery = useSpoolmanLocations();
  const lotNrFilterQuery = useSpoolmanLotNumbers();

  const allColumnsWithExtraFields = [
    ...allColumns,
    ...(extraFields.data?.map((field) => "extra." + field.key) ?? []),
    ...(filamentExtraFields.data?.map((field) => "filament.extra." + field.key) ?? []),
  ];

  // Load initial state
  const initialState = useInitialTableState(namespace);

  // State for the switch to the archived-spools view. On, the list shows ONLY archived
  // spools (server-side `archived=true` filter) — mixing archived rows into the active
  // list made it impossible to review just the archive.
  const [showArchived, setShowArchived] = useSavedState("spoolList-showArchived", false);

  // Fetch data from the API
  // To provide the live updates, we use a custom solution (useLiveify) instead of the built-in refine "liveMode" feature.
  // This is because the built-in feature does not call the liveProvider subscriber with a list of IDs, but instead
  // calls it with a list of filters, sorters, etc. This means the server-side has to support this, which is quite hard.
  // Free-text search across the spool's own fields and its filament's, sent as the server-side
  // `search` query param. Transient (not persisted) so a reload shows the full list. Issue #51.
  const [search, setSearch] = useState("");

  // Colour-similarity filter sent as color_hex + color_similarity_threshold (issue #46).
  const [colorFilter, setColorFilter] = useState<ColorSimilarityValue | undefined>(undefined);

  const { tableProps, sorters, setSorters, filters, setFilters, currentPage, pageSize, setCurrentPage } =
    useTable<ISpoolCollapsed>({
      meta: {
        queryParams: {
          ["allow_archived"]: showArchived,
          ...(showArchived ? { archived: true } : {}),
          ...(search ? { search } : {}),
          ...(colorFilter
            ? { color_hex: colorFilter.colorHex, color_similarity_threshold: colorFilter.threshold }
            : {}),
        },
      },
      syncWithLocation: false,
      pagination: {
        mode: "server",
        currentPage: initialState.pagination.currentPage,
        pageSize: initialState.pagination.pageSize,
      },
      sorters: {
        mode: "server",
        initial: initialState.sorters,
      },
      filters: {
        mode: "server",
        initial: initialState.filters,
      },
      liveMode: "manual",
      onLiveEvent(event) {
        if (event.type === "created" || event.type === "deleted") {
          // updated is handled by the liveify
          invalidate({
            resource: "spool",
            invalidates: ["list"],
          });
        }
      },
      queryOptions: {
        select(data) {
          return {
            total: data.total,
            data: data.data.map(collapseSpool),
          };
        },
      },
    });

  // Natural-language search (#362): the reply lands in the exact same state the user
  // could have set by hand - column filters, search box, color chip, archived view -
  // so every applied filter stays visible and editable through the normal controls.
  const applyAISearch = (aiFilters: AISearchFilters, dropped: string[]) => {
    const next: LogicalFilter[] = [];
    if (aiFilters.materials) next.push({ field: "filament.material", operator: "in", value: aiFilters.materials });
    if (aiFilters.vendors) next.push({ field: "filament.vendor.name", operator: "in", value: aiFilters.vendors });
    if (aiFilters.locations) next.push({ field: "location", operator: "in", value: aiFilters.locations });
    if (aiFilters.lot_numbers) next.push({ field: "lot_nr", operator: "in", value: aiFilters.lot_numbers });
    setFilters(next, "replace");
    setSearch(aiFilters.search ?? "");
    setColorFilter(aiFilters.color_hex ? { colorHex: aiFilters.color_hex, threshold: DEFAULT_THRESHOLD } : undefined);
    setShowArchived(aiFilters.archived === true);
    setCurrentPage(1);
    if (dropped.length > 0) {
      messageApi.info(t("aisearch.dropped", { parts: dropped.join(", ") }));
    }
  };

  // Create state for the columns to show
  const [showColumns, setShowColumns] = useState<string[]>(initialState.showColumns ?? defaultColumns);

  // User-defined column order (#94); undefined = the natural allColumns order (which also lets newly
  // added extra-field columns slot into their default position until the user rearranges).
  const [columnOrder, setColumnOrder] = useState<string[] | undefined>(initialState.columnOrder);

  // The order actually applied: the saved order (dropping any ids no longer present) followed by any
  // columns the saved order doesn't mention yet (e.g. freshly added extra fields), in natural order.
  const effectiveOrder = useMemo(
    () => computeEffectiveOrder(columnOrder, allColumnsWithExtraFields),
    [columnOrder, allColumnsWithExtraFields],
  );

  const moveColumn = (fromIndex: number, toIndex: number) => {
    setColumnOrder(moveInOrder(effectiveOrder, fromIndex, toIndex));
  };

  // User-set column widths (#90); merged over each column's default width and persisted per table.
  const [columnWidths, setColumnWidths] = useState<Record<string, number> | undefined>(initialState.columnWidths);
  const resizeColumn = (columnId: string, width: number) => {
    setColumnWidths({ ...(columnWidths ?? {}), [columnId]: Math.round(width) });
  };

  // Override each data column's width with the user's saved width and hand its id + resize callback to
  // the header cell so it can render a drag handle (#90). Id-less columns (actions) aren't resizable.
  const applyColumnWidths = <T extends { dataIndex?: unknown }>(cols: T[]): T[] =>
    cols.map((col) => {
      const id = columnIdOf(col);
      if (!id) return col;
      return {
        ...col,
        width: columnWidths?.[id] ?? (col as { width?: number | string }).width,
        onHeaderCell: () =>
          ({ columnId: id, onResize: resizeColumn }) as unknown as HTMLAttributes<HTMLTableCellElement>,
      } as T;
    });

  // Row selection drives the "Print Labels" toolbar action and the bulk-action bar (#73): with rows
  // selected, printing skips the in-page spool selector, and a contextual bar offers bulk edit/archive.
  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);
  const selectedIds = useMemo(() => selectedRowKeys.map(Number), [selectedRowKeys]);

  // Records of the selected rows, captured at selection time so the totals row can sum a
  // selection that spans pages (the table only holds the current page's rows).
  const [selectedRecords, setSelectedRecords] = useState<Map<number, ISpoolCollapsed>>(new Map());
  const onSelectionChange = useCallback((keys: Key[], rows: ISpoolCollapsed[]) => {
    setSelectedRowKeys(keys);
    setSelectedRecords((prev) => {
      const next = new Map(prev);
      // antd hands `undefined` for preserved keys whose rows are on other pages.
      rows.forEach((r) => r && next.set(r.id, r));
      const selected = new Set(keys.map(Number));
      for (const id of next.keys()) {
        if (!selected.has(id)) next.delete(id);
      }
      return next;
    });
  }, []);

  // After a bulk change, refetch the list so the rows reflect the new values and clear the selection.
  const onBulkApplied = useCallback(() => {
    invalidate({ resource: "spool", invalidates: ["list"] });
    setSelectedRowKeys([]);
  }, [invalidate]);
  const { openBulkEdit, bulkEditModal } = useSpoolBulkEditModal(locationOptions, messageApi, onBulkApplied);
  // Header-level weigh-many workflow (#99), independent of row selection.
  const { openBulkWeightUpdate, bulkWeightUpdateModal } = useBulkWeightUpdateModal(messageApi);

  // Bulk archive/unarchive: loop the single-spool PATCH over the selection (no bulk backend endpoint,
  // so the API surface integrations depend on is unchanged), behind a confirm.
  const bulkArchive = (archive: boolean) => {
    const ids = selectedIds;
    confirm({
      title: archive
        ? t("spool.bulk.archive_confirm", { count: ids.length })
        : t("spool.bulk.unarchive_confirm", { count: ids.length }),
      okText: archive ? t("buttons.archive") : t("buttons.unArchive"),
      okType: "primary",
      cancelText: t("buttons.cancel"),
      async onOk() {
        const failed = await bulkPatchSpools(ids, { archived: archive });
        if (failed === 0) {
          messageApi.success(t("spool.bulk.applied", { count: ids.length }));
        } else {
          messageApi.error(t("spool.bulk.applied_partial", { failed, count: ids.length }));
        }
        onBulkApplied();
      },
    });
  };

  // Store state in local storage
  const tableState: TableState = {
    sorters,
    filters,
    pagination: { currentPage: currentPage, pageSize },
    showColumns,
    columnOrder,
    columnWidths,
  };
  useStoreInitialState(namespace, tableState);

  // Collapse the dataSource to a mutable list
  const queryDataSource: ISpoolCollapsed[] = useMemo(
    () => (tableProps.dataSource || []).map((record) => ({ ...record })),
    [tableProps.dataSource],
  );
  const dataSource = useLiveify("spool", queryDataSource, collapseSpool);

  // Total matching rows, for the grid view's own pagination control (the Table reads it from
  // tableProps directly). Falls back to the shown count if the server total isn't present.
  const gridTotal =
    tableProps.pagination && typeof tableProps.pagination === "object"
      ? (tableProps.pagination.total ?? dataSource.length)
      : dataSource.length;

  // Optional grid/gallery view (#139): large colour tiles for picking a spool by colour. Off by
  // default (table), persisted, so it never changes the default look.
  const [viewMode, setViewMode] = useSavedState<"table" | "grid">("spoolList-viewMode", "table");

  // Always-on totals row (#134): sums the selected spools when a selection exists, otherwise the
  // currently-shown page (the list is server-paginated, so "everything" isn't loaded client-side).
  const totals = useMemo(() => {
    const selectionActive = selectedIds.length > 0;
    // Prefer the live table row over the snapshot taken at selection time, so inline edits
    // and websocket updates are reflected; the snapshot covers rows on other pages.
    const rows = selectionActive
      ? selectedIds
          .map((id) => dataSource.find((r) => r.id === id) ?? selectedRecords.get(id))
          .filter((r): r is ISpoolCollapsed => r !== undefined)
      : dataSource;
    let remaining = 0;
    let used = 0;
    let price = 0;
    for (const s of rows) {
      remaining += s.remaining_weight ?? 0;
      used += s.used_weight ?? 0;
      price += s.price ?? 0;
    }
    return { selectionActive, count: rows.length, remaining, used, price };
  }, [dataSource, selectedIds, selectedRecords]);

  // Function for opening an ant design modal that asks for confirmation for archiving a spool
  const archiveSpool = async (spool: ISpoolCollapsed, archive: boolean) => {
    try {
      await setSpoolArchived(spool, archive);
    } catch (error) {
      // Surface the failure (#227) - the row would otherwise just silently stay put.
      messageApi.error(error instanceof Error && error.message ? error.message : t("notifications.error"));
      return;
    }
    invalidate({
      resource: "spool",
      id: spool.id,
      invalidates: ["list", "detail"],
    });
  };

  const archiveSpoolPopup = async (spool: ISpoolCollapsed) => {
    // If the spool has no remaining weight, archive it immediately since it's likely not a mistake
    if (spool.remaining_weight != undefined && spool.remaining_weight <= 0) {
      await archiveSpool(spool, true);
    } else {
      confirm({
        title: t("spool.titles.archive"),
        content: t("spool.messages.archive"),
        okText: t("buttons.archive"),
        okType: "primary",
        cancelText: t("buttons.cancel"),
        onOk() {
          return archiveSpool(spool, true);
        },
      });
    }
  };

  if (tableProps.pagination) {
    tableProps.pagination.showSizeChanger = true;
  }

  const { editUrl, showUrl, cloneUrl } = useNavigation();
  const actions = useCallback(
    (record: ISpoolCollapsed) => {
      const actions: Action[] = [
        { name: t("buttons.show"), icon: <EyeOutlined />, link: showUrl("spool", record.id) },
        { name: t("buttons.edit"), icon: <EditOutlined />, link: editUrl("spool", record.id) },
        { name: t("buttons.clone"), icon: <PlusSquareOutlined />, link: cloneUrl("spool", record.id) },
        { name: t("spool.titles.adjust"), icon: <ToolOutlined />, onClick: () => openSpoolAdjustModal(record) },
      ];
      if (record.archived) {
        actions.push({
          name: t("buttons.unArchive"),
          icon: <ToTopOutlined />,
          onClick: () => archiveSpool(record, false),
        });
      } else {
        actions.push({ name: t("buttons.archive"), icon: <InboxOutlined />, onClick: () => archiveSpoolPopup(record) });
      }
      // User-configured action links (#140) open an external URL templated with the spool's fields.
      actionLinks.forEach((link) => {
        actions.push({
          name: link.name,
          icon: <LinkOutlined />,
          onClick: () => window.open(buildSpoolActionUrl(link.url, record), "_blank", "noopener,noreferrer"),
        });
      });
      return actions;
    },
    [t, editUrl, showUrl, cloneUrl, openSpoolAdjustModal, archiveSpool, archiveSpoolPopup, actionLinks],
  );

  const originalOnChange = tableProps.onChange;
  tableProps.onChange = (pagination, filters, sorter, extra) => {
    // Rename the filament name columns' filter keys to "filament.id": we sort on the name columns
    // (combined or standalone, #94) but filter by filament id, and antd/Refine only allow one field
    // for both.
    Object.keys(filters).forEach((key) => {
      if (key === "filament.combined_name" || key === "filament.name") {
        filters["filament.id"] = filters[key];
        delete filters[key];
      }
    });

    originalOnChange?.(pagination, filters, sorter, extra);
  };

  const commonProps = {
    t,
    navigate,
    actions,
    dataSource,
    tableState,
    sorter: true,
  };

  return (
    <List
      headerButtons={({ defaultButtons }) => (
        <>
          <Input.Search
            placeholder={t("buttons.search")}
            allowClear
            // Remount when the search state is set programmatically (AI search), so the
            // box always shows the text that is actually filtering the list.
            key={`search-${search}`}
            defaultValue={search}
            onSearch={(value) => {
              setSearch(value);
              setCurrentPage(1);
            }}
            onChange={(e) => {
              // Clearing the box (X or emptying it) immediately restores the full list.
              if (e.target.value === "") {
                setSearch("");
                setCurrentPage(1);
              }
            }}
            style={{ width: 200 }}
          />
          <AISearchButton entity="spool" onApply={applyAISearch} />
          <ColorSimilarityFilter
            value={colorFilter}
            onChange={(v) => {
              setColorFilter(v);
              setCurrentPage(1);
            }}
          />
          <Tooltip title={t("printing.qrcode.tooltip")}>
            <Button
              type="primary"
              icon={<PrinterOutlined />}
              onClick={() => {
                if (selectedRowKeys.length > 0) {
                  const params = new URLSearchParams();
                  selectedRowKeys.forEach((key) => params.append("spools", String(key)));
                  // The selection's job is done once it's in the URL; clear it so it
                  // doesn't linger when the user returns from printing.
                  setSelectedRowKeys([]);
                  navigate(`print?${params.toString()}`);
                } else {
                  navigate("print");
                }
              }}
            >
              {t("printing.qrcode.button")}
            </Button>
          </Tooltip>
          <Tooltip title={t("spool.weigh.tooltip")}>
            <Button icon={<ToolOutlined />} onClick={openBulkWeightUpdate}>
              {t("spool.weigh.button")}
            </Button>
          </Tooltip>
          <Tooltip title={showArchived ? t("buttons.hideArchivedTooltip") : t("buttons.showArchivedTooltip")}>
            <Button
              icon={<InboxOutlined />}
              type={showArchived ? "primary" : "default"}
              ghost={showArchived}
              onClick={() => {
                // The two views are disjoint sets, so a carried-over selection or page
                // number would be meaningless (or point past the end) in the other view.
                setShowArchived(!showArchived);
                setSelectedRowKeys([]);
                setCurrentPage(1);
              }}
            >
              {showArchived ? t("buttons.hideArchived") : t("buttons.showArchived")}
            </Button>
          </Tooltip>
          <Tooltip title={t("buttons.clearFiltersTooltip")}>
            <Button
              icon={<FilterOutlined />}
              onClick={() => {
                setFilters([], "replace");
                setSorters([{ field: "id", order: "asc" }]);
                setCurrentPage(1);
              }}
            >
              {t("buttons.clearFilters")}
            </Button>
          </Tooltip>
          {/* Grid/table view toggle (#139). */}
          <Tooltip title={viewMode === "grid" ? t("spool.view.table_tooltip") : t("spool.view.grid_tooltip")}>
            <Button
              icon={viewMode === "grid" ? <UnorderedListOutlined /> : <AppstoreOutlined />}
              onClick={() => setViewMode(viewMode === "grid" ? "table" : "grid")}
            >
              {viewMode === "grid" ? t("spool.view.table") : t("spool.view.grid")}
            </Button>
          </Tooltip>
          {/* The column manager only applies to the table, so hide it in grid view. */}
          {viewMode === "table" && (
            <ColumnManager
              buttonLabel={t("buttons.columns")}
              buttonTooltip={t("buttons.columnsTooltip")}
              visible={showColumns}
              onVisibleChange={setShowColumns}
              onReorder={moveColumn}
              columns={effectiveOrder.map((column_id) => {
                if (column_id.indexOf("filament.extra.") === 0) {
                  const field = filamentExtraFields.data?.find((f) => "filament.extra." + f.key === column_id);
                  return { id: column_id, label: field ? filamentColumnLabel(field.name) : column_id };
                }
                if (column_id.indexOf("extra.") === 0) {
                  const extraField = extraFields.data?.find((field) => "extra." + field.key === column_id);
                  return { id: column_id, label: extraField?.name ?? column_id };
                }
                return { id: column_id, label: t(translateColumnI18nKey(column_id)) };
              })}
            />
          )}
          {defaultButtons}
        </>
      )}
    >
      {messageContextHolder}
      {spoolAdjustModal}
      {bulkEditModal}
      {bulkWeightUpdateModal}
      {/* Contextual bulk-action bar (#73): only shown while rows are selected, so the list stays
          uncluttered when nothing is selected. */}
      {selectedRowKeys.length > 0 && (
        <Space className="spool-bulk-actions" style={{ marginBottom: 16 }} wrap>
          <span>{t("spool.bulk.selected", { count: selectedRowKeys.length })}</span>
          <Button icon={<EditOutlined />} onClick={() => openBulkEdit(selectedIds)}>
            {t("spool.bulk.edit")}
          </Button>
          {/* The archived view lists only archived spools and the active view only active ones,
              so exactly one of the two transitions is meaningful at a time. */}
          {showArchived ? (
            <Button icon={<ToTopOutlined />} onClick={() => bulkArchive(false)}>
              {t("buttons.unArchive")}
            </Button>
          ) : (
            <Button icon={<InboxOutlined />} onClick={() => bulkArchive(true)}>
              {t("buttons.archive")}
            </Button>
          )}
          <Button type="text" onClick={() => setSelectedRowKeys([])}>
            {t("spool.bulk.clear_selection")}
          </Button>
        </Space>
      )}
      {viewMode === "grid" ? (
        <>
          {/* Gallery view (#139): the same filtered/paginated data as large colour tiles. Read-only —
              switch back to the table for sorting, per-column filters, inline edit and selection. */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12 }}>
            {dataSource.map((record) => (
              <SpoolGalleryCard key={record.id} record={record} onClick={() => navigate(showUrl("spool", record.id))} />
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
            <Pagination
              current={currentPage}
              pageSize={pageSize}
              total={gridTotal}
              showSizeChanger={false}
              onChange={(page) => setCurrentPage(page)}
            />
          </div>
        </>
      ) : (
        <Table
          {...tableProps}
          sticky
          tableLayout="auto"
          scroll={{ x: "max-content" }}
          components={{ header: { cell: ResizableHeaderCell } }}
          summary={() => (
            <Table.Summary>
              <Table.Summary.Row>
                {/* Totals for the selection when one exists, else the shown page (server-paginated,
                    so the whole filtered set isn't client-side). One spanning cell keeps the row
                    robust against column reorder/resize/visibility. #134 */}
                <Table.Summary.Cell index={0} colSpan={showColumns.length + 2}>
                  <Space split="·" wrap>
                    <span>
                      {totals.selectionActive
                        ? t("spool.totals.selected", { count: totals.count })
                        : t("spool.totals.shown", { count: totals.count })}
                    </span>
                    <span>
                      {t("spool.fields.remaining_weight")}: {formatWeight(totals.remaining)}
                    </span>
                    <span>
                      {t("spool.fields.used_weight")}: {formatWeight(totals.used)}
                    </span>
                    <span>
                      {t("spool.fields.price")}: {currencyFormatter.format(totals.price)}
                    </span>
                  </Space>
                </Table.Summary.Cell>
              </Table.Summary.Row>
            </Table.Summary>
          )}
          dataSource={dataSource}
          rowKey="id"
          rowSelection={{
            selectedRowKeys,
            onChange: onSelectionChange,
            preserveSelectedRowKeys: true,
          }}
          // Make archived rows greyed out
          onRow={(record) => {
            if (record.archived) {
              return {
                style: {
                  fontStyle: "italic",
                  color: "#999",
                },
              };
            } else {
              return {};
            }
          }}
          columns={applyColumnWidths(
            orderColumns(
              removeUndefined([
                SortedColumn({
                  ...commonProps,
                  id: "id",
                  i18ncat: "spool",
                  width: 70,
                }),
                SpoolIconColumn({
                  ...commonProps,
                  id: "filament.combined_name",
                  i18nkey: "spool.fields.filament_name",
                  color: (record: ISpoolCollapsed) => getSpoolEffectiveColor(record),
                  dataId: "filament.combined_name",
                  filterValueQuery: filamentFilterQuery,
                  clickAffordance: true,
                }),
                FilteredQueryColumn({
                  ...commonProps,
                  id: "filament.vendor.name",
                  i18nkey: "spool.fields.vendor_name",
                  filterValueQuery: vendorFilterQuery,
                  width: 120,
                }),
                // Standalone filament name (#94): the Name half of the split, with the color icon. Opt-in;
                // pair with the Vendor column above and hide the combined name column for a two-column split.
                SpoolIconColumn({
                  ...commonProps,
                  id: "filament.name",
                  i18nkey: "spool.fields.filament_name_only",
                  color: (record: ISpoolCollapsed) => getSpoolEffectiveColor(record),
                  dataId: "filament.name",
                  filterValueQuery: filamentFilterQuery,
                  clickAffordance: true,
                }),
                FilteredQueryColumn({
                  ...commonProps,
                  id: "filament.material",
                  i18nkey: "spool.fields.material",
                  filterValueQuery: materialFilterQuery,
                  width: 120,
                }),
                // Opt-in colour column (#113): a swatch that sorts by the filament's hue. dataId names
                // the server sort key (filament.color_hue); the colour-similarity filter (#46) lives in
                // the toolbar, so this column is sort-only.
                SortedColumn({
                  ...commonProps,
                  id: "filament.color_hue",
                  i18nkey: "spool.fields.color",
                  align: "center",
                  width: 80,
                  render: (_, record: ISpoolCollapsed) => <SpoolIcon color={getSpoolEffectiveColor(record)} />,
                }),
                SortedColumn({
                  ...commonProps,
                  id: "price",
                  i18ncat: "spool",
                  align: "right",
                  width: 80,
                  render: (_, obj: ISpoolCollapsed) => (
                    <EditableNumberCell
                      resource="spool"
                      recordId={obj.id}
                      field="price"
                      editable={inlineEditEnabled}
                      messageApi={messageApi}
                      t={t}
                      value={obj.price ?? undefined}
                      precision={2}
                      align="right"
                      addonAfter={getCurrencySymbol(undefined, currency)}
                      display={obj.price === undefined || obj.price === null ? "" : currencyFormatter.format(obj.price)}
                    />
                  ),
                }),
                SortedColumn({
                  ...commonProps,
                  id: "used_weight",
                  i18ncat: "spool",
                  align: "right",
                  width: 110,
                  render: (_, obj: ISpoolCollapsed) => (
                    <EditableNumberCell
                      resource="spool"
                      recordId={obj.id}
                      field="used_weight"
                      editable={inlineEditEnabled}
                      messageApi={messageApi}
                      t={t}
                      value={obj.used_weight}
                      unit="g"
                      align="right"
                      display={
                        obj.used_weight === null || obj.used_weight === undefined ? (
                          <TextField value="" />
                        ) : (
                          <NumberFieldUnit
                            value={obj.used_weight}
                            unit="g"
                            autoScale={unitScaling}
                            options={{ maximumFractionDigits: 0, minimumFractionDigits: 0 }}
                          />
                        )
                      }
                    />
                  ),
                }),
                SortedColumn({
                  ...commonProps,
                  id: "remaining_weight",
                  i18ncat: "spool",
                  align: "right",
                  width: 110,
                  render: (_, obj: ISpoolCollapsed) => (
                    <EditableNumberCell
                      resource="spool"
                      recordId={obj.id}
                      field="remaining_weight"
                      editable={inlineEditEnabled}
                      messageApi={messageApi}
                      t={t}
                      value={obj.remaining_weight}
                      unit="g"
                      align="right"
                      display={
                        obj.remaining_weight === null || obj.remaining_weight === undefined ? (
                          <TextField value={t("unknown")} />
                        ) : (
                          <NumberFieldUnit
                            value={obj.remaining_weight}
                            unit="g"
                            autoScale={unitScaling}
                            options={{ maximumFractionDigits: 0, minimumFractionDigits: 0 }}
                          />
                        )
                      }
                    />
                  ),
                }),
                NumberColumn({
                  ...commonProps,
                  id: "spool_weight",
                  i18ncat: "spool",
                  unit: "g",
                  maxDecimals: 0,
                  defaultText: t("unknown"),
                  width: 110,
                  autoScale: unitScaling,
                }),
                NumberColumn({
                  ...commonProps,
                  id: "used_length",
                  i18ncat: "spool",
                  unit: "mm",
                  maxDecimals: 0,
                  width: 120,
                  autoScale: unitScaling,
                }),
                NumberColumn({
                  ...commonProps,
                  id: "remaining_length",
                  i18ncat: "spool",
                  unit: "mm",
                  maxDecimals: 0,
                  defaultText: t("unknown"),
                  width: 120,
                  autoScale: unitScaling,
                }),
                FilteredQueryColumn({
                  ...commonProps,
                  id: "location",
                  i18ncat: "spool",
                  filterValueQuery: locationFilterQuery,
                  width: 120,
                  render: (_, obj: ISpoolCollapsed) => (
                    <EditableSelectCell
                      resource="spool"
                      recordId={obj.id}
                      field="location"
                      editable={inlineEditEnabled}
                      messageApi={messageApi}
                      t={t}
                      value={obj.location}
                      options={locationOptions}
                      display={obj.location ?? ""}
                    />
                  ),
                }),
                FilteredQueryColumn({
                  ...commonProps,
                  id: "lot_nr",
                  i18ncat: "spool",
                  filterValueQuery: lotNrFilterQuery,
                  width: 120,
                }),
                DateColumn({
                  ...commonProps,
                  id: "first_used",
                  i18ncat: "spool",
                  width: 130,
                }),
                DateColumn({
                  ...commonProps,
                  id: "last_used",
                  i18ncat: "spool",
                  width: 130,
                }),
                DateColumn({
                  ...commonProps,
                  id: "registered",
                  i18ncat: "spool",
                  width: 130,
                }),
                ...(extraFields.data?.map((field) => {
                  return CustomFieldColumn({
                    ...commonProps,
                    field,
                  });
                }) ?? []),
                // #83: the filament's own custom fields, read-only and namespaced under "filament".
                ...(filamentExtraFields.data?.map((field) => {
                  return CustomFieldColumn({
                    ...commonProps,
                    field,
                    entityPrefix: ["filament"],
                    title: filamentColumnLabel(field.name),
                  });
                }) ?? []),
                SortedColumn({
                  ...commonProps,
                  id: "comment",
                  i18ncat: "spool",
                  width: 150,
                  render: (_, obj: ISpoolCollapsed) => (
                    <EditableTextCell
                      resource="spool"
                      recordId={obj.id}
                      field="comment"
                      editable={inlineEditEnabled}
                      messageApi={messageApi}
                      t={t}
                      value={obj.comment}
                      maxLength={1024}
                      display={enrichText(obj.comment)}
                    />
                  ),
                }),
                ActionsColumn(t("table.actions"), actions),
              ]),
              effectiveOrder,
            ),
          )}
        />
      )}
    </List>
  );
};

export default SpoolList;
